#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云班课辅助工具 —— 图形界面（tkinter）。

界面布局对应原易语言版本的窗口：账号密码 → 登录 → 选择课程 → 资源列表
→ 一键已读。所有网络请求都跑在后台线程里，通过队列回传消息给主线程刷新，
避免界面卡死。

启动方式：``python main.py gui`` 或 ``python gui.py``。
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import api
import config

__all__ = ["run", "YunBanKeApp"]

LOG = logging.getLogger("yunbanke.gui")

# 界面配色（浅色）
BG = "#f5f6f8"
CARD = "#ffffff"
ACCENT = "#7166F0"
OK_COLOR = "#1a9c5b"
FAIL_COLOR = "#d93b3b"
MUTED = "#6b7280"


class YunBanKeApp(ttk.Frame):
    """主窗口。"""

    def __init__(
        self,
        master: tk.Tk,
        *,
        config_path: str | None = None,
        timeout: float = 15.0,
        delay: float = 0.3,
    ) -> None:
        super().__init__(master, padding=12)
        self.master = master  # type: ignore[assignment]
        self.config_path = config_path
        self.timeout = timeout
        self.delay = delay

        self.client: api.YunBanKeClient | None = None
        self.courses: list[api.Course] = []
        self.res_ids: list[str] = []
        self.busy = False
        self.stop_flag = threading.Event()
        self.msg_queue: queue.Queue[tuple] = queue.Queue()

        self._build_widgets()
        self._load_saved_credentials()
        self.after(100, self._drain_queue)

    # ---------------------------------------------------------------- #
    # 界面
    # ---------------------------------------------------------------- #

    def _build_widgets(self) -> None:
        self.pack(fill="both", expand=True)
        self.master.title("云班课辅助工具 · 资源一键已读")
        self.master.configure(bg=BG)
        self.master.minsize(760, 560)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:  # pragma: no cover
            pass
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground="#1f2937")
        style.configure("Card.TLabel", background=CARD, foreground="#1f2937")
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED)
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
        style.configure("Treeview", rowheight=24)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))

        # ---- 登录区 ----
        login = ttk.Frame(self, style="Card.TFrame", padding=12)
        login.pack(fill="x")
        login.columnconfigure(1, weight=1)

        ttk.Label(login, text="账号", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.var_account = tk.StringVar()
        ttk.Entry(login, textvariable=self.var_account).grid(
            row=0, column=1, sticky="ew", padx=(8, 12), pady=2
        )

        ttk.Label(login, text="密码", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        self.var_password = tk.StringVar()
        ttk.Entry(login, textvariable=self.var_password, show="●").grid(
            row=0, column=3, sticky="ew", padx=(8, 12), pady=2
        )
        login.columnconfigure(3, weight=1)

        self.var_save = tk.BooleanVar(value=True)
        ttk.Checkbutton(login, text="记住密码", variable=self.var_save).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        self.btn_login = ttk.Button(
            login, text="登录", style="Accent.TButton", command=self.on_login
        )
        self.btn_login.grid(row=0, column=4, rowspan=2, padx=(0, 0), ipadx=18, sticky="ns")

        self.var_status = tk.StringVar(value="未登录")
        ttk.Label(login, textvariable=self.var_status, style="Muted.TLabel").grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(8, 0)
        )

        # ---- 课程区 ----
        course = ttk.Frame(self, style="Card.TFrame", padding=12)
        course.pack(fill="x", pady=(10, 0))
        course.columnconfigure(1, weight=1)

        ttk.Label(course, text="课程", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.var_course = tk.StringVar()
        self.combo_course = ttk.Combobox(
            course, textvariable=self.var_course, state="readonly"
        )
        self.combo_course.grid(row=0, column=1, sticky="ew", padx=8)
        self.combo_course.bind("<<ComboboxSelected>>", lambda _e: self.on_course_selected())

        self.btn_refresh = ttk.Button(course, text="刷新课程", command=self.on_refresh_courses)
        self.btn_refresh.grid(row=0, column=2, padx=(0, 6))

        self.btn_load_res = ttk.Button(course, text="获取资源", command=self.on_load_resources)
        self.btn_load_res.grid(row=0, column=3)

        # ---- 操作区 ----
        actions = ttk.Frame(self, style="Card.TFrame", padding=12)
        actions.pack(fill="x", pady=(10, 0))
        actions.columnconfigure(2, weight=1)

        self.btn_start = ttk.Button(
            actions, text="一键已读", style="Accent.TButton", command=self.on_start
        )
        self.btn_start.grid(row=0, column=0, ipadx=16)

        self.btn_stop = ttk.Button(actions, text="停止", command=self.on_stop, state="disabled")
        self.btn_stop.grid(row=0, column=1, padx=8)

        self.progress = ttk.Progressbar(actions, mode="determinate")
        self.progress.grid(row=0, column=2, sticky="ew", padx=(4, 10))

        self.var_progress = tk.StringVar(value="0 / 0")
        ttk.Label(actions, textvariable=self.var_progress, style="Card.TLabel").grid(
            row=0, column=3
        )

        # ---- 资源列表 ----
        list_frame = ttk.Frame(self, style="Card.TFrame", padding=(12, 12, 12, 6))
        list_frame.pack(fill="both", expand=True, pady=(10, 0))
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            list_frame,
            columns=("no", "res_id", "status"),
            show="headings",
            height=10,
        )
        self.tree.heading("no", text="#")
        self.tree.heading("res_id", text="资源 ID")
        self.tree.heading("status", text="状态")
        self.tree.column("no", width=52, anchor="center", stretch=False)
        self.tree.column("res_id", width=380)
        self.tree.column("status", width=150, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)

        self.tree.tag_configure("ok", foreground=OK_COLOR)
        self.tree.tag_configure("fail", foreground=FAIL_COLOR)
        self.tree.tag_configure("pending", foreground=MUTED)

        # ---- 日志 ----
        log_frame = ttk.Frame(self, style="Card.TFrame", padding=(12, 6, 12, 12))
        log_frame.pack(fill="both")
        log_frame.columnconfigure(0, weight=1)

        self.txt_log = tk.Text(
            log_frame,
            height=7,
            wrap="word",
            relief="flat",
            bg="#fbfbfd",
            fg="#374151",
            font=("Consolas", 9),
        )
        self.txt_log.grid(row=0, column=0, sticky="ew")
        self.txt_log.configure(state="disabled")

    # ---------------------------------------------------------------- #
    # 辅助
    # ---------------------------------------------------------------- #

    def _load_saved_credentials(self) -> None:
        saved = config.load_credentials(self.config_path)
        if saved:
            self.var_account.set(saved.account)
            self.var_password.set(saved.password)
            self.log(f"已从 {config.config_path(self.config_path)} 载入保存的账号")

    def log(self, message: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", message.rstrip() + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in (self.btn_login, self.btn_refresh, self.btn_load_res, self.btn_start):
            widget.configure(state=state)
        self.btn_stop.configure(state="normal" if busy else "disabled")
        if not busy:
            self.combo_course.configure(state="readonly" if self.courses else "disabled")

    def _client_or_warn(self) -> api.YunBanKeClient | None:
        if self.client is None or not self.client.is_authenticated:
            messagebox.showwarning("提示", "请先登录。")
            return None
        return self.client

    def _run_in_thread(self, target, *args, **kwargs) -> None:
        thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        thread.start()

    # ---------------------------------------------------------------- #
    # 事件
    # ---------------------------------------------------------------- #

    def on_login(self) -> None:
        account = self.var_account.get().strip()
        password = self.var_password.get()
        if not account or not password:
            messagebox.showwarning("提示", "请输入账号和密码。")
            return

        self.set_busy(True)
        self.var_status.set("正在登录…")
        self.log("─ 正在登录…")
        self._run_in_thread(self._task_login, account, password)

    def _task_login(self, account: str, password: str) -> None:
        try:
            client = api.YunBanKeClient(timeout=self.timeout, delay=self.delay)
            user = client.login(account, password)
        except api.YunBanKeError as exc:
            self.msg_queue.put(("login_failed", str(exc)))
            return
        except Exception as exc:  # pragma: no cover
            self.msg_queue.put(("login_failed", f"未知错误：{exc}"))
            return

        self.msg_queue.put(("logged_in", client, user))

        if self.var_save.get():
            try:
                path = config.save_credentials(account, password, self.config_path)
                self.msg_queue.put(("log", f"凭证已保存到 {path}"))
            except OSError as exc:
                self.msg_queue.put(("log", f"保存凭证失败：{exc}"))
        else:
            self.msg_queue.put(("log", "未保存凭证（未勾选「记住密码」）"))

        try:
            courses = client.get_my_courses()
            self.msg_queue.put(("courses", courses))
        except api.YunBanKeError as exc:
            self.msg_queue.put(("log", f"读取课程列表失败：{exc}"))
            self.msg_queue.put(("task_finished",))

    def on_refresh_courses(self) -> None:
        client = self._client_or_warn()
        if client is None:
            return
        self.set_busy(True)
        self.log("─ 正在获取课程列表…")
        self._run_in_thread(self._task_load_courses, client)

    def _task_load_courses(self, client: api.YunBanKeClient) -> None:
        try:
            courses = client.get_my_courses()
        except api.YunBanKeError as exc:
            self.msg_queue.put(("log", f"获取课程失败：{exc}"))
            self.msg_queue.put(("task_finished",))
            return
        self.msg_queue.put(("courses", courses))

    def on_course_selected(self) -> None:
        self.res_ids = []
        self._clear_tree()
        self.var_progress.set("0 / 0")
        self.progress.configure(value=0)

    def on_load_resources(self) -> None:
        client = self._client_or_warn()
        course = self._current_course()
        if client is None or course is None:
            return
        self.set_busy(True)
        self.log(f"─ 正在获取「{course.display_name}」的资源列表…")
        self._run_in_thread(self._task_load_resources, client, course)

    def _task_load_resources(self, client: api.YunBanKeClient, course: api.Course) -> None:
        try:
            res_ids = client.get_resource_ids(course.id)
        except api.YunBanKeError as exc:
            self.msg_queue.put(("log", f"获取资源失败：{exc}"))
            self.msg_queue.put(("task_finished",))
            return
        self.msg_queue.put(("resources", res_ids))

    def on_start(self) -> None:
        client = self._client_or_warn()
        course = self._current_course()
        if client is None or course is None:
            return

        if self.res_ids and not messagebox.askyesno(
            "确认", f"即将对「{course.display_name}」的 {len(self.res_ids)} 条资源标记已读，继续？"
        ):
            return

        self.stop_flag.clear()
        self.set_busy(True)
        self._clear_tree()
        self.var_progress.set("0 / 0")
        self.progress.configure(value=0)
        self.log(f"─ 开始一键已读：{course.display_name}")
        self._run_in_thread(self._task_mark_read, client, course)

    def _task_mark_read(self, client: api.YunBanKeClient, course: api.Course) -> None:
        try:
            res_ids = self.res_ids or client.get_resource_ids(course.id)
            if not self.res_ids:
                self.msg_queue.put(("resources", res_ids))
            self.msg_queue.put(("progress", 0, len(res_ids)))

            def on_progress(done: int, total: int, result: api.ResourceResult) -> None:
                self.msg_queue.put(("resource", done, result))
                self.msg_queue.put(("progress", done, total))
                # 停止按钮：置位后让客户端抛异常中断当前循环
                if self.stop_flag.is_set():
                    raise api.YunBanKeError("已按用户请求停止")

            report = client.mark_course_read(course, res_ids=res_ids, progress=on_progress)
            self.msg_queue.put(("report", report))
        except api.YunBanKeError as exc:
            self.msg_queue.put(("log", f"任务结束：{exc}"))
        finally:
            self.msg_queue.put(("task_finished",))

    def on_stop(self) -> None:
        self.stop_flag.set()
        self.log("─ 正在停止，等待当前请求结束…")

    # ---------------------------------------------------------------- #
    # 队列消费
    # ---------------------------------------------------------------- #

    def _current_course(self) -> api.Course | None:
        index = self.combo_course.current()
        if index < 0 or index >= len(self.courses):
            messagebox.showwarning("提示", "请先选择课程。")
            return None
        return self.courses[index]

    def _clear_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _set_row_status(self, index: int, result: api.ResourceResult) -> None:
        children = self.tree.get_children()
        if index - 1 >= len(children):
            return
        item = children[index - 1]
        tag = "ok" if result.ok else "fail"
        text = "✓ " + result.detail if result.ok else "✗ " + result.detail
        self.tree.item(item, values=(index, result.res_id, text), tags=(tag,))

    def _drain_queue(self) -> None:
        try:
            while True:
                message = self.msg_queue.get_nowait()
                kind = message[0]

                if kind == "log":
                    self.log(message[1])

                elif kind == "logged_in":
                    client, user = message[1], message[2]
                    self.client = client
                    self.var_status.set(
                        f"已登录：{user.display_name}"
                        + (f"（{user.student_no}）" if user.student_no else "")
                    )
                    self.log(f"登录成功：{user.display_name}")

                elif kind == "login_failed":
                    self.var_status.set("登录失败")
                    self.log(f"登录失败：{message[1]}")
                    self.set_busy(False)
                    messagebox.showerror("登录失败", message[1])

                elif kind == "courses":
                    self.courses = message[1]
                    labels = [f"{c.name}（{c.id}）" if c.name else c.id for c in self.courses]
                    self.combo_course.configure(values=labels)
                    if labels:
                        self.combo_course.current(0)
                        self.on_course_selected()
                        self.combo_course.configure(state="readonly")
                    self.log(f"共获取到 {len(self.courses)} 门课程")
                    self.set_busy(False)
                    self.var_status.set(f"已登录 · {len(self.courses)} 门课程")

                elif kind == "resources":
                    self.res_ids = message[1]
                    self._clear_tree()
                    for index, res_id in enumerate(self.res_ids, start=1):
                        self.tree.insert(
                            "", "end", values=(index, res_id, "待处理"), tags=("pending",)
                        )
                    self.var_progress.set(f"0 / {len(self.res_ids)}")
                    self.log(f"解析到 {len(self.res_ids)} 条资源")
                    self.set_busy(False)

                elif kind == "resource":
                    self._set_row_status(message[1], message[2])

                elif kind == "progress":
                    done, total = message[1], message[2]
                    self.progress.configure(maximum=max(total, 1), value=done)
                    self.var_progress.set(f"{done} / {total}")

                elif kind == "report":
                    report: api.MarkReport = message[1]
                    self.log(report.summary())
                    if report.ok:
                        messagebox.showinfo("完成", report.summary())
                    else:
                        messagebox.showwarning("完成（存在失败）", report.summary())

                elif kind == "task_finished":
                    self.set_busy(False)

        except queue.Empty:
            pass

        self.after(100, self._drain_queue)

    # ---------------------------------------------------------------- #

    def on_close(self) -> None:
        self.stop_flag.set()
        self.master.destroy()


def run(
    config: str | None = None,
    timeout: float = 15.0,
    delay: float = 0.3,
) -> int:
    """启动图形界面。"""
    root = tk.Tk()
    try:  # 高 DPI 下别糊
        from ctypes import windll  # type: ignore[attr-defined]

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # pragma: no cover
        pass

    app = YunBanKeApp(root, config_path=config, timeout=timeout, delay=delay)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
