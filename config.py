#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置与凭证存取。

原易语言版本把账号密码明文写在程序目录的 ``username.ini`` 里，本模块保留
同名文件（方便老用户平滑迁移），但对文件格式做了容错：既支持标准 ini 的
``[节]`` 写法，也支持最朴素的 ``key=value`` 逐行写法。

.. warning::
   ``username.ini`` 里保存的是明文密码，务必不要提交到 Git。
   仓库自带的 ``.gitignore`` 已经把它排除掉了。
"""

from __future__ import annotations

import configparser
import logging
import os
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Credentials", "config_path", "load_credentials", "save_credentials",
           "clear_credentials"]

log = logging.getLogger("yunbanke.config")

#: 项目根目录（本文件所在目录）
PROJECT_ROOT = Path(__file__).resolve().parent
CREDENTIAL_FILE = "username.ini"
SECTION = "yunbanke"

_KEY_ALIASES = {
    "account": "account",
    "username": "account",
    # 原易语言程序里的变量名就是这个拼写（少了一个 r），老文件可能沿用
    "usernane": "account",
    "user_name": "account",
    "user": "account",
    "账号": "account",
    "用户名": "account",
    "password": "password",
    "passwd": "password",
    "pwd": "password",
    "密码": "password",
}


@dataclass
class Credentials:
    """一对账号密码。"""

    account: str = ""
    password: str = ""

    def __bool__(self) -> bool:
        return bool(self.account and self.password)


def config_path(path: str | os.PathLike[str] | None = None) -> Path:
    """返回凭证文件路径。"""
    if path is not None:
        return Path(path).expanduser()
    return PROJECT_ROOT / CREDENTIAL_FILE


def _parse_raw(text: str) -> dict[str, str]:
    """把 ini 文本解析成扁平字典，忽略大小写与节名。"""
    result: dict[str, str] = {}

    def absorb(key: str, value: str) -> None:
        alias = _KEY_ALIASES.get(key.strip().lower())
        if alias and value.strip():
            result.setdefault(alias, value.strip())

    # 优先按标准 ini 解析
    parser = configparser.ConfigParser()
    try:
        if parser.read_string(text):
            for section in parser.sections():
                for key, value in parser.items(section):
                    absorb(key, value)
    except configparser.Error:
        pass

    # 再按裸 key=value 兜底（老版本写的文件可能没有节）
    for line in text.splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line or line.startswith(("#", ";", "[")):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        absorb(key, value)

    return result


def load_credentials(path: str | os.PathLike[str] | None = None) -> Credentials:
    """读取本地保存的账号密码；文件不存在时返回空凭证。"""
    file = config_path(path)
    if not file.is_file():
        return Credentials()

    try:
        text = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 易语言默认写 GBK，兜底试一次
        text = file.read_text(encoding="gbk", errors="replace")
    except OSError as exc:
        log.warning("读取 %s 失败：%s", file, exc)
        return Credentials()

    data = _parse_raw(text)
    return Credentials(
        account=data.get("account", ""), password=data.get("password", "")
    )


def save_credentials(
    account: str,
    password: str,
    path: str | os.PathLike[str] | None = None,
) -> Path:
    """保存账号密码到 ``username.ini``。"""
    file = config_path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"# 云班课辅助工具凭证文件\n"
        f"# 明文保存，请勿提交到版本库或分享给他人\n"
        f"[{SECTION}]\n"
        f"account={account}\n"
        f"password={password}\n"
    )
    file.write_text(content, encoding="utf-8")
    try:
        os.chmod(file, 0o600)
    except OSError:  # pragma: no cover - Windows 上意义有限
        pass
    log.info("凭证已保存到 %s", file)
    return file


def clear_credentials(path: str | os.PathLike[str] | None = None) -> bool:
    """删除凭证文件，返回是否真的删掉了。"""
    file = config_path(path)
    if not file.is_file():
        return False
    file.unlink()
    log.info("已删除 %s", file)
    return True
