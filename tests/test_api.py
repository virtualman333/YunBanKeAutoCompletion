#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线单元测试：不需要网络，也不会碰真实账号。

用 ``python -m unittest discover -s tests -v`` 运行。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import config  # noqa: E402


class FakeResponse:
    """最小化的响应替身。"""

    def __init__(self, text: str, status_code: int = 200):
        self._text = text
        self.status_code = status_code
        self.content = text.encode("utf-8")
        self.url = "https://example.invalid/"

    @property
    def text(self) -> str:
        return self._text

    def json(self):
        return json.loads(self._text)


class FakeSession:
    """记录所有请求并返回预设响应。"""

    def __init__(self, responses: list[FakeResponse] | None = None):
        self.headers: dict[str, str] = {}
        self.cookies = __import__("requests").cookies.RequestsCookieJar()
        self.responses = list(responses or [])
        self.calls: list[dict] = []

    def mount(self, *_args, **_kwargs) -> None:  # 兼容 HTTPAdapter 挂载
        pass

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError(f"没有预置响应，却被请求了：{method} {url}")
        return self.responses.pop(0)


SPA_HTML = (
    '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
    '<link rel="stylesheet" href="/web/styles/site.css"></head><body></body></html>'
)


def make_client(responses: list[FakeResponse]) -> tuple[api.YunBanKeClient, FakeSession]:
    session = FakeSession(responses)
    client = api.YunBanKeClient(session=session, delay=0, retries=0)
    return client, session


class TestCourseParsing(unittest.TestCase):
    def test_parses_documented_shape(self):
        """原版用的 data[i].course.name / data[i].id 结构。"""
        payload = {
            "status": True,
            "data": [
                {"id": "aaaaaaaa-1111-1111-1111-111111111111", "course": {"name": "计算机网络"}},
                {"id": "bbbbbbbb-2222-2222-2222-222222222222", "course": {"name": "操作系统"}},
            ],
        }
        courses = api.YunBanKeClient._parse_courses(payload)
        self.assertEqual([c.name for c in courses], ["计算机网络", "操作系统"])
        self.assertEqual(courses[0].id, "aaaaaaaa-1111-1111-1111-111111111111")

    def test_tolerates_alternate_keys(self):
        payload = {
            "data": [
                {"clazz_course_id": "cccccccc-3333-3333-3333-333333333333", "name": "数据结构"},
                {"course_id": "dddddddd-4444-4444-4444-444444444444", "course_name": "编译原理"},
            ]
        }
        courses = api.YunBanKeClient._parse_courses(payload)
        self.assertEqual([c.name for c in courses], ["数据结构", "编译原理"])

    def test_ignores_items_without_id(self):
        payload = {"data": [{"course": {"name": "没有 ID 的课"}}, "不是字典"]}
        self.assertEqual(api.YunBanKeClient._parse_courses(payload), [])

    def test_unknown_structure_returns_empty(self):
        self.assertEqual(api.YunBanKeClient._parse_courses({"foo": "bar"}), [])


class TestResourceIdExtraction(unittest.TestCase):
    COURSE = "36b5d14a-956f-11ec-80ab-b8599fe847b4"

    def test_extracts_data_value_like_original(self):
        html = (
            f'<li data-value="aaaa1111-0000-0000-0000-000000000001" data-course="{self.COURSE}">A</li>'
            f'<li data-value="aaaa1111-0000-0000-0000-000000000002">B</li>'
        )
        ids = api.YunBanKeClient._extract_res_ids(html, self.COURSE)
        self.assertEqual(
            ids,
            [
                "aaaa1111-0000-0000-0000-000000000001",
                "aaaa1111-0000-0000-0000-000000000002",
            ],
        )

    def test_deduplicates_and_preserves_order(self):
        rid = "aaaa1111-0000-0000-0000-000000000001"
        html = f'<i data-value="{rid}"></i><i data-value="{rid}"></i>'
        self.assertEqual(api.YunBanKeClient._extract_res_ids(html, self.COURSE), [rid])

    def test_never_returns_course_id(self):
        html = f'<i data-value="{self.COURSE}"></i>'
        self.assertEqual(api.YunBanKeClient._extract_res_ids(html, self.COURSE), [])

    def test_falls_back_to_json_payload(self):
        html = 'var data = {"res_id":"aaaa1111-0000-0000-0000-000000000009"};'
        self.assertEqual(
            api.YunBanKeClient._extract_res_ids(html, self.COURSE),
            ["aaaa1111-0000-0000-0000-000000000009"],
        )

    def test_loose_fallback_picks_any_uuid(self):
        html = "<div>没有任何已知属性 aaaa1111-0000-0000-0000-000000000007</div>"
        self.assertEqual(
            api.YunBanKeClient._extract_res_ids(html, self.COURSE),
            ["aaaa1111-0000-0000-0000-000000000007"],
        )


class TestLogin(unittest.TestCase):
    def test_success_sets_cookie_and_user(self):
        body = json.dumps(
            {
                "status": True,
                "token": "tok-123",
                "user": {
                    "userId": "u-1",
                    "fullName": "张三",
                    "studentNo": "2023001",
                    "nickName": "小张",
                    "userType": 1,
                },
            }
        )
        client, session = make_client([FakeResponse(body)])
        user = client.login("13800000000", "pw")

        self.assertEqual(user.display_name, "张三")
        self.assertEqual(user.student_no, "2023001")
        self.assertTrue(client.is_authenticated)
        self.assertEqual(session.calls[0]["json"], {"account": "13800000000", "password": "pw"})

    def test_wrong_password_raises_login_error(self):
        body = json.dumps(
            {
                "errorMessage": "你输入的账号或密码不正确",
                "errorCode": "err.invalid.userPassword",
                "status": False,
            }
        )
        client, _ = make_client([FakeResponse(body)])
        with self.assertRaises(api.LoginError) as ctx:
            client.login("13800000000", "bad")
        self.assertIn("账号或密码不正确", str(ctx.exception))

    def test_missing_token_raises_api_error(self):
        client, _ = make_client([FakeResponse(json.dumps({"status": True}))])
        with self.assertRaises(api.ApiError):
            client.login("13800000000", "pw")

    def test_token_nested_in_data(self):
        client, _ = make_client(
            [FakeResponse(json.dumps({"status": True, "data": {"token": "nested-tok"}}))]
        )
        client.login("13800000000", "pw")
        self.assertEqual(client.token, "nested-tok")

    def test_html_response_means_session_expired(self):
        client, _ = make_client([FakeResponse(SPA_HTML)])
        client.set_token("tok")
        with self.assertRaises(api.SessionExpiredError):
            client.get_my_courses()


class TestMarkRead(unittest.TestCase):
    def _client(self):
        ok = FakeResponse(json.dumps({"success": True}))
        preview = FakeResponse(json.dumps({"url": "https://example.invalid/f.mp4"}))
        return make_client([preview, ok, preview, ok])

    def test_sends_expected_fields(self):
        client, session = self._client()
        client.set_token("tok")
        report = client.mark_course_read(
            api.Course(id="course-1", name="测试课"),
            res_ids=["res-1", "res-2"],
        )

        self.assertEqual((report.total, report.succeeded, report.failed), (2, 2, 0))
        self.assertTrue(report.ok)

        preview_call = session.calls[0]
        self.assertEqual(preview_call["params"]["m"], "request_url_for_json")
        self.assertEqual(
            preview_call["data"],
            {"file_id": "res-1", "type": "VIEW", "clazz_course_id": "course-1"},
        )
        self.assertEqual(preview_call["headers"]["mime"], "video")

        mark_call = session.calls[1]
        self.assertEqual(mark_call["params"]["m"], "save_watch_to")
        self.assertEqual(mark_call["data"]["watch_to"], str(api.DEFAULT_WATCH_TO))
        self.assertEqual(mark_call["data"]["duration"], str(api.DEFAULT_WATCH_TO))
        self.assertEqual(mark_call["data"]["current_watch_to"], str(api.DEFAULT_WATCH_TO))

    def test_progress_callback_reports_each_item(self):
        client, _ = self._client()
        client.set_token("tok")
        seen: list[tuple[int, int, bool]] = []

        client.mark_course_read(
            "course-1",
            res_ids=["res-1", "res-2"],
            progress=lambda done, total, result: seen.append((done, total, result.ok)),
        )
        self.assertEqual(seen, [(1, 2, True), (2, 2, True)])

    def test_failure_recorded_without_stopping(self):
        client, _ = make_client(
            [
                FakeResponse(json.dumps({"url": "x"})),
                FakeResponse(json.dumps({"success": False, "errorMessage": "无权限"})),
            ]
        )
        client.set_token("tok")
        report = client.mark_course_read("course-1", res_ids=["res-1"])
        self.assertEqual(report.failed, 1)
        self.assertFalse(report.ok)
        self.assertIn("无权限", report.results[0].detail)

    def test_success_heuristics(self):
        self.assertTrue(api.YunBanKeClient.is_success({"success": True}))
        self.assertTrue(api.YunBanKeClient.is_success({"success": "true"}))
        self.assertFalse(api.YunBanKeClient.is_success({"success": False}))
        self.assertFalse(api.YunBanKeClient.is_success({"errorMessage": "挂了"}))
        self.assertTrue(api.YunBanKeClient.is_success({"ok": 1}))

    def test_limit_truncates(self):
        client, _ = make_client(
            [
                FakeResponse(json.dumps({"url": "x"})),
                FakeResponse(json.dumps({"success": True})),
            ]
        )
        client.set_token("tok")
        report = client.mark_course_read("course-1", res_ids=["a", "b", "c"], limit=1)
        self.assertEqual(report.total, 1)


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.environ.get("TEMP", ".")) / "_ybk_test_username.ini"
        if self.tmp.exists():
            self.tmp.unlink()

    def tearDown(self):
        if self.tmp.exists():
            self.tmp.unlink()

    def test_roundtrip(self):
        config.save_credentials("13800000000", "secret", self.tmp)
        creds = config.load_credentials(self.tmp)
        self.assertEqual((creds.account, creds.password), ("13800000000", "secret"))
        self.assertTrue(creds)

    def test_reads_legacy_bare_keys(self):
        """老版本易语言写的文件可能没有节名，甚至用 usernane 这种拼写。"""
        self.tmp.write_text("usernane=13800000000\npassword=secret\n", encoding="utf-8")
        creds = config.load_credentials(self.tmp)
        self.assertEqual(creds.account, "13800000000")
        self.assertEqual(creds.password, "secret")

    def test_missing_file_returns_empty(self):
        self.assertFalse(config.load_credentials(self.tmp))

    def test_clear(self):
        config.save_credentials("a", "b", self.tmp)
        self.assertTrue(config.clear_credentials(self.tmp))
        self.assertFalse(config.clear_credentials(self.tmp))


if __name__ == "__main__":
    unittest.main(verbosity=2)
