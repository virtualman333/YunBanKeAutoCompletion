#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云班课辅助工具 —— 命令行入口。

.. code-block:: text

    python main.py login                  # 首次登录并记住账号
    python main.py courses                # 列出我加入的课程
    python main.py read --all             # 全部课程一键已读
    python main.py read --course 1        # 只处理第 1 门课程
    python main.py gui                    # 启动图形界面

运行 ``python main.py <子命令> --help`` 可以看每个子命令的完整参数。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Sequence

import api
import config

__version__ = "2.0.0"

LOG = logging.getLogger("yunbanke")


# --------------------------------------------------------------------------- #
# 终端输出小工具
# --------------------------------------------------------------------------- #


def _setup_console() -> None:
    """让 Windows 控制台也能正常输出中文与符号。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    # 第三方库的 DEBUG 日志太吵，屏蔽掉
    for noisy in ("urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def rule(title: str = "", width: int = 68) -> str:
    if not title:
        return "─" * width
    return f"── {title} " + "─" * max(0, width - len(title) - 4)


# --------------------------------------------------------------------------- #
# 组装客户端
# --------------------------------------------------------------------------- #


def build_client(args: argparse.Namespace) -> api.YunBanKeClient:
    """根据命令行参数构造并登录客户端。"""
    client = api.YunBanKeClient(
        timeout=args.timeout,
        delay=args.delay,
        retries=0 if args.no_retry else 3,
    )

    # 1) 直接给 token：跳过登录
    if getattr(args, "token", None):
        client.set_token(args.token)
        LOG.info("已使用命令行提供的 token")
        return client

    # 2) 命令行给了账号密码 / 3) 读本地 username.ini
    saved = config.load_credentials(args.config)
    account = args.account or saved.account
    password = args.password or saved.password

    if not account or not password:
        raise SystemExit(
            "缺少登录凭证。\n"
            "  首次使用请先执行：python main.py login\n"
            "  或直接传入：python main.py <命令> --account 手机号 --password 密码"
        )

    try:
        client.login(account, password)
    except api.LoginError as exc:
        raise SystemExit(f"登录失败：{exc}") from exc

    # 登录成功且是命令行新给的密码，就顺手记下来（--no-save 可关闭）
    if not args.no_save and (account != saved.account or password != saved.password):
        try:
            config.save_credentials(account, password, args.config)
        except OSError as exc:
            LOG.warning("保存凭证失败：%s", exc)

    return client


def resolve_course(
    client: api.YunBanKeClient, selector: str
) -> api.Course:
    """把用户给的 ``--course`` 值解析成课程对象。

    支持三种写法：序号（``1``）、课程 ID（完整 UUID）、课程名关键字。
    """
    courses = client.get_my_courses()
    if not courses:
        raise SystemExit("当前账号下没有查到任何课程。")

    # 序号
    if selector.isdigit():
        index = int(selector)
        if not 1 <= index <= len(courses):
            raise SystemExit(
                f"课程序号 {index} 超出范围，当前只有 {len(courses)} 门课程。"
            )
        return courses[index - 1]

    # 完整 ID
    for course in courses:
        if course.id.lower() == selector.lower():
            return course

    # 名称关键字
    matched = [c for c in courses if selector in c.name]
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        names = "、".join(f"{c.name}({c.id})" for c in matched)
        raise SystemExit(f"关键字「{selector}」匹配到多门课程，请改用序号或 ID：{names}")

    raise SystemExit(f"没有找到匹配「{selector}」的课程，可用 python main.py courses 查看。")


# --------------------------------------------------------------------------- #
# 各子命令
# --------------------------------------------------------------------------- #


def cmd_login(args: argparse.Namespace) -> int:
    saved = config.load_credentials(args.config)
    account = args.account or saved.account
    password = args.password or saved.password

    if not account:
        account = input("云班课账号（手机号/学号）：").strip()
    if not password:
        import getpass

        password = getpass.getpass("密码：")
    if not account or not password:
        print("账号和密码都不能为空。")
        return 1

    client = api.YunBanKeClient(timeout=args.timeout)
    try:
        user = client.login(account, password)
    except api.LoginError as exc:
        print(f"✗ 登录失败：{exc}")
        return 1
    except api.YunBanKeError as exc:
        print(f"✗ 登录出错：{exc}")
        return 1

    print(rule("登录成功"))
    print(f"  姓名    {user.display_name}")
    print(f"  学号    {user.student_no or '-'}")
    print(f"  用户 ID {user.user_id or '-'}")
    print(f"  令牌    {client.token[:8]}…（已存入内存，仅本次运行有效）")

    if args.no_save:
        print("\n未保存凭证（--no-save）。")
    else:
        path = config.save_credentials(account, password, args.config)
        print(f"\n凭证已保存到 {path}")
        print("该文件是明文，请勿提交到 Git 或分享给他人。")

    try:
        courses = client.get_my_courses()
    except api.YunBanKeError as exc:
        print(f"\n（读取课程列表失败：{exc}）")
        return 0

    print(f"\n共 {len(courses)} 门课程：")
    for index, course in enumerate(courses, start=1):
        print(f"  {index:>2}. {course.display_name}")
    return 0


def cmd_courses(args: argparse.Namespace) -> int:
    client = build_client(args)
    courses = client.get_my_courses()

    if not courses:
        print("没有查到课程。")
        return 0

    print(rule(f"我加入的课程（{len(courses)} 门）"))
    width = max((len(c.name) for c in courses), default=4)
    for index, course in enumerate(courses, start=1):
        print(f"  {index:>2}. {course.name:<{width}}  {course.id}")
    print(rule())
    print("提示：python main.py read --course <序号|ID>  可对单门课程执行一键已读")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    client = build_client(args)

    if args.all:
        targets_desc = "全部课程"
        courses = client.get_my_courses()
    else:
        if not args.course:
            raise SystemExit("请用 --course <序号|ID|名称> 指定课程，或用 --all 处理全部课程。")
        courses = [resolve_course(client, args.course)]
        targets_desc = courses[0].display_name

    print(rule(f"开始一键已读：{targets_desc}"))
    print(f"  观看进度上报值 {args.watch_to} 秒   请求间隔 {args.delay}s")
    print(rule())

    exit_code = 0
    for course in courses:
        def on_progress(done: int, total: int, result: api.ResourceResult) -> None:
            mark = "✓" if result.ok else "✗"
            tail = "" if result.ok else f"  {result.detail}"
            print(f"  [{done:>3}/{total}] {mark} {result.res_id}{tail}", flush=True)

        try:
            report = client.mark_course_read(
                course,
                watch_to=args.watch_to,
                limit=args.limit,
                progress=on_progress,
            )
        except api.SessionExpiredError as exc:
            print(f"\n✗ 会话失效：{exc}")
            return 2
        except api.YunBanKeError as exc:
            print(f"\n✗ 处理「{course.display_name}」失败：{exc}")
            exit_code = 1
            continue

        print(f"\n{report.summary()}")
        if report.failed:
            exit_code = 1
            print("  失败明细：")
            for item in report.results:
                if not item.ok:
                    print(f"    - {item.res_id}  {item.detail}")
        print(rule())

    print("任务结束：" + ("全部成功 ✓" if exit_code == 0 else "存在失败项，请查看上面的日志"))
    return exit_code


def cmd_logout(args: argparse.Namespace) -> int:
    if config.clear_credentials(args.config):
        print(f"已删除 {config.config_path(args.config)}")
    else:
        print("本地没有保存凭证。")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        import gui
    except ImportError as exc:  # pragma: no cover
        print(f"无法加载图形界面：{exc}")
        return 1
    return gui.run(config=args.config, timeout=args.timeout, delay=args.delay)


# --------------------------------------------------------------------------- #
# 参数解析
# --------------------------------------------------------------------------- #


def _add_common_options(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    """注册公共参数。

    :param suppress: 为 ``True`` 时把所有默认值设成 ``argparse.SUPPRESS``。
        子解析器必须这么做——否则它会把默认值写回命名空间，把用户写在
        子命令**前面**的同名参数覆盖掉（argparse 的经典坑）。
    """

    def default(value):
        return argparse.SUPPRESS if suppress else value

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=default(False),
        help="输出调试日志",
    )
    parser.add_argument(
        "--account",
        default=default(None),
        help="云班课账号（手机号/学号），不填则读取 username.ini",
    )
    parser.add_argument("--password", default=default(None), help="云班课密码，不填则读取 username.ini")
    parser.add_argument("--token", default=default(None), help="直接使用已有 login_token，跳过登录")
    parser.add_argument(
        "--timeout", type=float, default=default(15.0), help="单次请求超时秒数（默认 15）"
    )
    parser.add_argument(
        "--delay", type=float, default=default(0.3), help="相邻请求间隔秒数（默认 0.3）"
    )
    parser.add_argument(
        "--no-retry",
        action="store_true",
        default=default(False),
        help="关闭传输层自动重试（默认重试 3 次）",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        default=default(False),
        help="登录成功后不把凭证写入 username.ini",
    )
    parser.add_argument(
        "--config", default=default(None), help=f"凭证文件路径（默认 {config.config_path()}）"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="云班课辅助工具 —— 课程资源一键已读",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python main.py login\n"
            "  python main.py courses\n"
            "  python main.py read --course 1\n"
            "  python main.py read --all --limit 5\n"
            "  python main.py --account 13800000000 read --course 1\n"
            "  python main.py gui\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _add_common_options(parser, suppress=False)

    # 同一批参数再挂到每个子命令上，这样写在子命令前后都能识别
    common = argparse.ArgumentParser(add_help=False)
    _add_common_options(common, suppress=True)

    sub = parser.add_subparsers(dest="command", metavar="<子命令>")

    sub.add_parser("login", parents=[common], help="登录并保存账号密码").set_defaults(
        func=cmd_login
    )
    sub.add_parser("courses", parents=[common], help="列出我加入的课程").set_defaults(
        func=cmd_courses
    )
    sub.add_parser("logout", parents=[common], help="删除本地保存的凭证").set_defaults(
        func=cmd_logout
    )
    sub.add_parser("gui", parents=[common], help="启动图形界面").set_defaults(func=cmd_gui)

    read = sub.add_parser(
        "read", parents=[common], help="把课程资源标记为已读"
    )
    read.add_argument("--course", metavar="<序号|ID|名称>", help="指定课程")
    read.add_argument("--all", action="store_true", help="处理全部课程")
    read.add_argument(
        "--watch-to",
        type=int,
        default=api.DEFAULT_WATCH_TO,
        help=f"上报的观看秒数（默认 {api.DEFAULT_WATCH_TO}）",
    )
    read.add_argument("--limit", type=int, help="每门课程最多处理 N 条资源（试跑用）")
    read.add_argument("--dump-html", metavar="PATH", help="把资源页原始 HTML 写到文件后退出")
    read.set_defaults(func=cmd_read)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    # --dump-html 是排障用的旁路：只抓页面，不做已读
    if getattr(args, "dump_html", None) and args.command == "read":
        client = build_client(args)
        course = resolve_course(client, args.course) if args.course else None
        if course is None:
            raise SystemExit("--dump-html 需要同时指定 --course")
        ids = client.get_resource_ids(course.id, dump_path=args.dump_html)
        print(f"已导出 {args.dump_html}，解析到 {len(ids)} 条资源：")
        for rid in ids[:20]:
            print("  ", rid)
        if len(ids) > 20:
            print(f"   … 另外 {len(ids) - 20} 条")
        return 0

    try:
        return int(args.func(args) or 0)
    except api.SessionExpiredError as exc:
        print(f"\n✗ 会话失效：{exc}\n  请重新执行 python main.py login")
        return 2
    except api.YunBanKeError as exc:
        print(f"\n✗ 出错：{exc}")
        return 1
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
