# -*- coding: utf-8 -*-
"""文件日志：写入程序目录下的 logs/ 文件夹（按天分文件）。

GUI 不再显示日志面板，所有运行日志（进度、警告、完整性提示等）
统一落盘到 <程序目录>/logs/epubforge-YYYY-MM-DD.log。
"""

from __future__ import annotations

import datetime
import os
import sys


def log_dir() -> str:
    """日志目录：程序目录/logs；打包成 exe 时为 exe 所在目录/logs。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "logs")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:  # 程序目录不可写时退回用户主目录
        d = os.path.join(os.path.expanduser("~"), ".epubforge", "logs")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            return ""
    return d


def log(msg: str) -> None:
    """追加一行带时间戳的日志。"""
    d = log_dir()
    if not d:
        return
    try:
        day = datetime.date.today().isoformat()
        path = os.path.join(d, f"epubforge-{day}.log")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {msg}\n")
    except OSError:
        pass
