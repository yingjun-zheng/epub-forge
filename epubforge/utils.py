# -*- coding: utf-8 -*-
"""通用工具：编码探测、文本清理、HTML 转义。"""

from __future__ import annotations

import html
import re
from pathlib import Path

# 常见文本编码探测顺序（TXT / MD 等纯文本）
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "utf-16", "gb18030", "gbk", "big5", "latin-1")

_WS_RE = re.compile(r"[ \t\u3000]+")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def read_text_with_fallback(path: str | Path) -> tuple[str, str]:
    """读取文本文件，自动探测编码。返回 (text, used_encoding)。

    探测顺序：BOM → UTF-8 → UTF-16（NUL 密度启发式）→ GB18030 → GBK → Big5 → latin-1。
    GB18030/GBK 几乎能解码任意字节序列，必须放在 UTF-16 之后，否则 UTF-16
    文件会被误判成乱码（内容看似丢失/残缺）。
    """
    data = Path(path).read_bytes()
    # 1) BOM 明确指示
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16"), "utf-16"
    # 2) UTF-8（含 UTF-8 BOM）
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    # 3) UTF-16 启发式：大量 NUL 字节 → 几乎可以确定是 UTF-16（无 BOM）
    if data.count(b"\x00") > max(len(data) // 8, 4):
        try:
            return data.decode("utf-16"), "utf-16"
        except (UnicodeDecodeError, LookupError):
            pass
    # 4) 中文单字节/双字节编码
    for enc in ("gb18030", "gbk", "big5"):
        try:
            return data.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    # 5) 终极兜底：latin-1 永不失败
    return data.decode("latin-1"), "latin-1"


def clean_text(s: str) -> str:
    """清理空白与多余换行。"""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\u00a0", " ").replace("\u3000", " ")
    lines = [_WS_RE.sub(" ", ln).rstrip() for ln in s.split("\n")]
    # 去掉空行之间的多余空行
    out: list[str] = []
    prev_blank = False
    for ln in lines:
        blank = not ln.strip()
        if blank and prev_blank:
            continue
        out.append(ln)
        prev_blank = blank
    return "\n".join(out).strip("\n")


def escape_html(s: str) -> str:
    """转义为 HTML 文本节点内容。"""
    return html.escape(s, quote=False)


def para_html(text: str) -> str:
    """普通段落文本 → <p> 片段（保留内部换行）。"""
    parts = [escape_html(ln) for ln in text.split("\n")]
    return "<p>" + "<br/>".join(parts) + "</p>"


def slugify(title: str, fallback: str = "ch") -> str:
    """把标题转成安全的文件名片段（EPUB 内部文件名用）。"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    return (s or fallback)[:48]


def infer_title_from_filename(path: str | Path) -> str:
    """从文件名推断书名：去掉扩展名与常见修饰。"""
    name = Path(path).stem
    name = re.sub(r"[\s_\-—]+(最终版|终稿|修订版|v\d+(\.\d+)*|第[\d一二三四五六七八九十]+版)$", "", name)
    return name.strip() or "未命名文档"


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"
