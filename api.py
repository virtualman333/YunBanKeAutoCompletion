#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云班课（Mosoteach）接口客户端。

本模块把原易语言版本里散落在 ``获取资源列表`` / ``预览资源`` / ``观看视频``
几个子程序中的请求逻辑，统一封装成一个可复用的客户端类。

对接的四个接口：

======================================================  ==========================================
功能                                                    接口
======================================================  ==========================================
登录                                                    ``POST coreapi-proxy.mosoteach.cn/.../passports/account-login``
我加入的课程                                            ``GET  www.mosoteach.cn/web/index.php?c=clazzcourse&m=my_joined``
课程资源列表                                            ``GET  www.mosoteach.cn/web/index.php?c=res&m=index&clazz_course_id=<id>``
资源预览（取文件地址）                                  ``POST www.mosoteach.cn/web/index.php?c=res&m=request_url_for_json``
标记已读（写入观看进度）                                ``POST www.mosoteach.cn/web/index.php?c=res&m=save_watch_to``
======================================================  ==========================================

登录成功后服务端下发的令牌以 ``login_token=<token>`` 的形式放在 Cookie 里，
后续所有请求都依赖它，因此本模块统一用同一个 :class:`requests.Session` 维持会话。
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Sequence

import requests
from requests.adapters import HTTPAdapter

try:  # urllib3 2.x 与 1.x 的导入路径一致，但老版本 requests 可能没有
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    Retry = None  # type: ignore[assignment]

__all__ = [
    "YunBanKeError",
    "LoginError",
    "SessionExpiredError",
    "ApiError",
    "User",
    "Course",
    "ResourceResult",
    "MarkReport",
    "YunBanKeClient",
    "DEFAULT_WATCH_TO",
]

log = logging.getLogger("yunbanke.api")

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

WEB_ENDPOINT = "https://www.mosoteach.cn/web/index.php"
LOGIN_ENDPOINT = (
    "https://coreapi-proxy.mosoteach.cn/index.php/passports/account-login"
)

#: 与原版易语言程序保持一致的移动端 UA
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 11_0 like Mac OS X) "
    "AppleWebKit/604.1.38 (KHTML, like Gecko) Version/11.0 Mobile/15A372 Safari/604.1"
)

#: 写入观看进度时使用的秒数。原版硬编码为 12222，同时作为 duration 上报，
#: 等价于「把这一条资源标记成 100% 学完」。
DEFAULT_WATCH_TO = 12222

#: 资源 ID 的形态（云班课全站使用标准 UUID）
UUID_RE = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)

#: 从课程资源页 HTML 中抽取资源 ID 的正则，按优先级从精确到宽泛排列。
#: 第一条即原易语言程序里使用的 ``data-value="(.*?)"``。
RES_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r'data-value\s*=\s*"([0-9A-Fa-f-]{36})"'),
    re.compile(r"data-value\s*=\s*'([0-9A-Fa-f-]{36})'"),
    re.compile(r'data-res-id\s*=\s*"([0-9A-Fa-f-]{36})"'),
    re.compile(r'data-resource-id\s*=\s*"([0-9A-Fa-f-]{36})"'),
    re.compile(r'res_id\s*[=:]\s*"?([0-9A-Fa-f-]{36})"?'),
    re.compile(r'"res_id"\s*:\s*"([0-9A-Fa-f-]{36})"'),
)

#: 判断课程 ID 用的正则，用于在页面里兜底区分资源与课程
_MY_JOINED_HINT = ("login", "passport", "signin", "登录")


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #


class YunBanKeError(Exception):
    """本模块所有异常的基类。"""


class LoginError(YunBanKeError):
    """账号或密码不正确，或登录接口返回了业务错误。"""


class SessionExpiredError(YunBanKeError):
    """会话已失效（令牌过期 / 未登录）。

    典型表现是：期望返回 JSON 的接口返回了 SPA 的 HTML 外壳。
    """


class ApiError(YunBanKeError):
    """接口返回了非预期内容。"""


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #


@dataclass
class User:
    """登录用户。"""

    user_id: str = ""
    full_name: str = ""
    nick_name: str = ""
    student_no: str = ""
    avatar_url: str = ""
    user_type: Any = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def display_name(self) -> str:
        return self.full_name or self.nick_name or self.user_id or "未知用户"


@dataclass
class Course:
    """一门课程。``id`` 即接口里的 ``clazz_course_id``。"""

    id: str
    name: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def display_name(self) -> str:
        return self.name or self.id


@dataclass
class ResourceResult:
    """单条资源的处理结果。"""

    res_id: str
    ok: bool
    detail: str = ""


@dataclass
class MarkReport:
    """一次「一键已读」任务的汇总。"""

    course_id: str
    course_name: str
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list[ResourceResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.total > 0

    def summary(self) -> str:
        if self.total == 0:
            return f"「{self.course_name}」没有找到可标记的资源"
        return (
            f"「{self.course_name}」共 {self.total} 条资源，"
            f"成功 {self.succeeded} 条，失败 {self.failed} 条"
        )


# --------------------------------------------------------------------------- #
# 客户端
# --------------------------------------------------------------------------- #


class YunBanKeClient:
    """云班课接口客户端。

    :param timeout: 单次请求超时（秒）。
    :param retries: 传输层重试次数（连接失败 / 5xx）。
    :param delay: 每次请求之间的间隔（秒）。原版是死循环高频调用，
        这里默认留一点间隔，避免给服务端造成压力、也降低被风控的概率。
    :param user_agent: 请求 UA，默认移动端。
    :param session: 可注入自定义 :class:`requests.Session`（便于测试）。
    """

    def __init__(
        self,
        timeout: float = 15.0,
        retries: int = 3,
        delay: float = 0.3,
        user_agent: str = MOBILE_UA,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.delay = max(0.0, delay)
        self.user_agent = user_agent

        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

        if Retry is not None and retries > 0:
            retry = Retry(
                total=retries,
                connect=retries,
                read=retries,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET", "POST"}),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry)
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)

        self._user: User | None = None
        self._last_request_at = 0.0

    # ---------------------------------------------------------------- #
    # 基础请求
    # ---------------------------------------------------------------- #

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        """发一次请求，统一做限速、日志与基础错误处理。"""
        self._throttle()
        log.debug("%s %s params=%s data=%s", method, url, params, data)
        try:
            resp = self.session.request(
                method,
                url,
                params=params,
                data=data,
                json=json_body,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ApiError(f"请求失败：{url} -> {exc}") from exc
        finally:
            self._last_request_at = time.monotonic()

        log.debug("<- %s %s (%d bytes)", resp.status_code, resp.url, len(resp.content))
        return resp

    @staticmethod
    def _looks_like_spa(html: str) -> bool:
        """判断返回的是不是未登录时那个 SPA 外壳页面。"""
        head = html[:2000].lower()
        if "<!doctype html" not in head:
            return False
        return "/web/styles/site.css" in head or "static-cdn-oss.mosoteach.cn" in head

    def _json_or_raise(self, resp: requests.Response, what: str) -> dict[str, Any]:
        """把响应解析成 JSON，解析不了就抛出可读的异常。"""
        text = resp.text.lstrip("\ufeff \t\r\n")
        if text.startswith("{"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ApiError(f"{what} 返回的 JSON 无法解析：{exc}") from exc
            if isinstance(payload, dict):
                return payload
        if self._looks_like_spa(text) or "<html" in text[:500].lower():
            raise SessionExpiredError(
                f"{what} 返回的是网页而不是数据，通常意味着会话已失效。"
                f"请重新登录；若刚登录过，请用 --dump-html 导出原始响应排查。"
            )
        raise ApiError(f"{what} 返回了非预期内容：{text[:200]!r}")

    # ---------------------------------------------------------------- #
    # 登录 / 会话
    # ---------------------------------------------------------------- #

    @property
    def token(self) -> str | None:
        """当前会话令牌。"""
        return self.session.cookies.get("login_token")

    @property
    def user(self) -> User | None:
        return self._user

    @property
    def is_authenticated(self) -> bool:
        return bool(self.token)

    def set_token(self, token: str) -> None:
        """直接使用已有令牌（跳过登录），便于复用抓包得到的会话。"""
        if not token:
            raise ValueError("token 不能为空")
        self.session.cookies.set("login_token", token, domain=".mosoteach.cn")

    def login(self, account: str, password: str) -> User:
        """登录并返回用户信息。

        :raises LoginError: 账号密码错误。
        """
        if not account or not password:
            raise ValueError("账号和密码都不能为空")

        resp = self._request(
            "POST",
            LOGIN_ENDPOINT,
            json_body={"account": account, "password": password},
            headers={"Content-Type": "application/json"},
        )
        payload = self._json_or_raise(resp, "登录接口")

        # 服务端用 status=false + errorMessage 表达业务错误
        status = payload.get("status")
        if status is False or str(status).lower() == "false":
            message = payload.get("errorMessage") or payload.get("error_code") or "登录失败"
            raise LoginError(str(message))

        token = self._extract_token(payload)
        if not token:
            raise ApiError(
                "登录成功但响应里没有找到 token，"
                f"接口字段可能已变更。原始响应：{json.dumps(payload, ensure_ascii=False)[:300]}"
            )

        self.set_token(token)
        self._user = self._parse_user(payload.get("user") or {})
        log.info(
            "登录成功：%s（%s）", self._user.display_name, self._user.student_no or "-"
        )
        return self._user

    @staticmethod
    def _extract_token(payload: dict[str, Any]) -> str:
        """在响应里找令牌，兼容常见的几种嵌套层级。"""
        candidates: list[Any] = [
            payload.get("token"),
            payload.get("login_token"),
            payload.get("access_token"),
        ]
        for container in ("data", "result", "payload"):
            value = payload.get(container)
            if isinstance(value, dict):
                candidates += [
                    value.get("token"),
                    value.get("login_token"),
                    value.get("access_token"),
                ]
        for value in candidates:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _parse_user(raw: dict[str, Any]) -> User:
        user = User(raw=raw)
        mapping = {
            "userId": "user_id",
            "fullName": "full_name",
            "nickName": "nick_name",
            "studentNo": "student_no",
            "fullAvatarUrl": "avatar_url",
            "userType": "user_type",
        }
        for src, dst in mapping.items():
            value = raw.get(src)
            if value is not None:
                setattr(user, dst, str(value))
        return user

    def check_session(self) -> User:
        """验证当前会话是否仍然有效，顺便刷新用户信息。"""
        if not self.is_authenticated:
            raise SessionExpiredError("尚未登录，请先调用 login() 或 set_token()")
        courses = self.get_my_courses()
        if self._user is None:
            self._user = User()
        log.info("会话有效，共 %d 门课程", len(courses))
        return self._user

    # ---------------------------------------------------------------- #
    # 课程
    # ---------------------------------------------------------------- #

    def get_my_courses(self) -> list[Course]:
        """获取「我加入的课程」列表。"""
        resp = self._request(
            "GET",
            WEB_ENDPOINT,
            params={"c": "clazzcourse", "m": "my_joined"},
        )
        payload = self._json_or_raise(resp, "我的课程接口")
        return self._parse_courses(payload)

    @staticmethod
    def _parse_courses(payload: dict[str, Any]) -> list[Course]:
        """兼容 ``data[i].course.name`` / ``data[i].id`` 及其变体。"""
        items: Any = payload.get("data")
        if isinstance(items, dict):
            for key in ("list", "items", "courses", "rows"):
                if isinstance(items.get(key), list):
                    items = items[key]
                    break
        if not isinstance(items, list):
            for key in ("courses", "list", "data"):
                if isinstance(payload.get(key), list):
                    items = payload[key]
                    break
        if not isinstance(items, list):
            log.warning(
                "课程列表结构无法识别，原始响应：%s",
                json.dumps(payload, ensure_ascii=False)[:300],
            )
            return []

        courses: list[Course] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            inner = item.get("course") if isinstance(item.get("course"), dict) else {}

            course_id = (
                item.get("id")
                or item.get("clazz_course_id")
                or item.get("course_id")
                or inner.get("id")
                or ""
            )
            name = (
                inner.get("name")
                or item.get("name")
                or item.get("course_name")
                or ""
            )
            course_id = str(course_id).strip()
            name = str(name).strip()

            if not course_id:
                log.debug("跳过缺少课程 ID 的条目：%s", item)
                continue
            if not UUID_RE.fullmatch(course_id):
                log.debug("课程 ID 不是标准 UUID，仍按原值使用：%r", course_id)

            courses.append(Course(id=course_id, name=name, raw=item))

        log.info("获取到 %d 门课程", len(courses))
        return courses

    # ---------------------------------------------------------------- #
    # 资源
    # ---------------------------------------------------------------- #

    def get_resource_ids(
        self,
        course_id: str,
        *,
        dump_path: str | None = None,
    ) -> list[str]:
        """拉取课程资源页并解析出资源 ID 列表。

        :param course_id: 课程 ID（``clazz_course_id``）。
        :param dump_path: 若提供，则把原始 HTML 写到该文件，便于排查。
        """
        if not course_id:
            raise ValueError("course_id 不能为空")

        resp = self._request(
            "GET",
            WEB_ENDPOINT,
            params={"c": "res", "m": "index", "clazz_course_id": course_id},
        )
        html = resp.text

        if dump_path:
            try:
                with open(dump_path, "w", encoding="utf-8") as fh:
                    fh.write(html)
                log.info("原始响应已写入 %s", dump_path)
            except OSError as exc:  # pragma: no cover
                log.warning("写入 %s 失败：%s", dump_path, exc)

        res_ids = self._extract_res_ids(html, course_id)
        if not res_ids:
            if self._looks_like_spa(html):
                raise SessionExpiredError(
                    "资源页返回的是登录前的网页外壳，会话可能已失效，请重新登录。"
                )
            raise ApiError(
                "资源页里没有解析到任何资源 ID，可能是课程为空、"
                "或页面结构已调整。请用 --dump-html 导出页面后反馈。"
            )

        log.info("课程 %s 解析到 %d 条资源", course_id, len(res_ids))
        return res_ids

    @staticmethod
    def _extract_res_ids(html: str, course_id: str) -> list[str]:
        """从 HTML 中按优先级抽取资源 ID，去重且保持页面顺序。"""
        found: list[str] = []
        seen: set[str] = set()

        for pattern in RES_ID_PATTERNS:
            for match in pattern.finditer(html):
                value = match.group(1)
                if value not in seen:
                    seen.add(value)
                    found.append(value)
            if found:
                # 命中精确模式就不再退到更宽泛的规则，避免把课程 ID 混进来
                break

        if not found:
            # 兜底：页面里所有 UUID 都当作候选，但排除课程本身
            for match in UUID_RE.finditer(html):
                value = match.group(0)
                if value == course_id or value in seen:
                    continue
                seen.add(value)
                found.append(value)

        # 去掉课程 ID 自身
        return [rid for rid in found if rid != course_id]

    # ---------------------------------------------------------------- #
    # 已读
    # ---------------------------------------------------------------- #

    def preview_resource(self, res_id: str, course_id: str) -> dict[str, Any]:
        """请求资源预览地址（``request_url_for_json``）。

        这一步告诉服务端「我打开了这条资源」，也是原版程序在写进度前
        必做的动作。
        """
        resp = self._request(
            "POST",
            WEB_ENDPOINT,
            params={"c": "res", "m": "request_url_for_json"},
            data={
                "file_id": res_id,
                "type": "VIEW",
                "clazz_course_id": course_id,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "mime": "video",
            },
        )
        try:
            payload = resp.json()
        except ValueError:
            log.debug("预览接口未返回 JSON：%s", resp.text[:200])
            return {"raw": resp.text}
        return payload if isinstance(payload, dict) else {"raw": payload}

    def mark_read(
        self,
        res_id: str,
        course_id: str,
        *,
        watch_to: int = DEFAULT_WATCH_TO,
    ) -> dict[str, Any]:
        """把一条资源标记为已读 / 已学完（``save_watch_to``）。

        :param watch_to: 上报的观看秒数，同时作为 ``duration`` 与
            ``current_watch_to``，三者一致即代表进度 100%。
        """
        resp = self._request(
            "POST",
            WEB_ENDPOINT,
            params={"c": "res", "m": "save_watch_to"},
            data={
                "clazz_course_id": course_id,
                "res_id": res_id,
                "watch_to": str(watch_to),
                "duration": str(watch_to),
                "current_watch_to": str(watch_to),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            payload = resp.json()
        except ValueError:
            return {"raw": resp.text}
        return payload if isinstance(payload, dict) else {"raw": payload}

    @staticmethod
    def is_success(payload: dict[str, Any]) -> bool:
        """判断 ``save_watch_to`` 的响应是否表示成功。"""
        if "success" in payload:
            return bool(payload["success"]) and str(payload["success"]).lower() != "false"
        # 没有 success 字段时，用「是否存在错误码」兜底
        if payload.get("errorCode") or payload.get("errorMessage"):
            return False
        if payload.get("status") is False:
            return False
        return not payload.get("raw")

    def mark_course_read(
        self,
        course: Course | str,
        *,
        course_name: str = "",
        res_ids: Sequence[str] | None = None,
        watch_to: int = DEFAULT_WATCH_TO,
        limit: int | None = None,
        progress: Callable[[int, int, ResourceResult], None] | None = None,
        continue_on_error: bool = True,
    ) -> MarkReport:
        """把一个课程下所有资源标记为已读。

        :param course: :class:`Course` 对象或课程 ID 字符串。
        :param res_ids: 已经取到的资源 ID 列表；不传则内部再拉一次资源页。
        :param limit: 只处理前 N 条，便于小范围试跑。
        :param progress: 回调 ``(已完成数, 总数, 本次结果)``，GUI 用它刷新界面。
        :param continue_on_error: 单条失败后是否继续；否则立刻抛出。
        """
        if isinstance(course, Course):
            course_id, name = course.id, course.name or course_name
        else:
            course_id, name = course, course_name

        ids: list[str] = list(res_ids) if res_ids is not None else self.get_resource_ids(course_id)
        if limit is not None and limit > 0:
            ids = ids[:limit]

        report = MarkReport(
            course_id=course_id, course_name=name or course_id, total=len(ids)
        )

        for index, res_id in enumerate(ids, start=1):
            try:
                self.preview_resource(res_id, course_id)
                payload = self.mark_read(res_id, course_id, watch_to=watch_to)
                ok = self.is_success(payload)
                detail = "已标记为已读" if ok else f"接口未确认：{payload}"
            except YunBanKeError as exc:
                if not continue_on_error:
                    raise
                ok, detail = False, str(exc)

            result = ResourceResult(res_id=res_id, ok=ok, detail=detail)
            report.results.append(result)
            if ok:
                report.succeeded += 1
            else:
                report.failed += 1

            log.info(
                "[%d/%d] %s %s", index, len(ids), res_id, "✓" if ok else f"✗ {detail}"
            )
            if progress is not None:
                progress(index, len(ids), result)

        return report

    def mark_all_courses_read(self, **kwargs: Any) -> list[MarkReport]:
        """遍历当前账号下的全部课程并逐一标记已读。"""
        courses = self.get_my_courses()
        reports: list[MarkReport] = []
        for course in courses:
            log.info("开始处理课程：%s（%s）", course.display_name, course.id)
            reports.append(self.mark_course_read(course, **kwargs))
        return reports
