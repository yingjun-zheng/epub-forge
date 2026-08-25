# -*- coding: utf-8 -*-
"""扫描版 PDF 的 OCR 支持（RapidOCR + ONNX Runtime，纯本地离线）。

用法:
    from .ocr import PdfOcr
    ocr = PdfOcr()
    items = ocr.page_blocks(fitz_page)   # -> list[(kind, text)]，kind ∈ {'heading','para'}

依赖: rapidocr_onnxruntime / onnxruntime / opencv-python / numpy
      （可通过 tools/fetch_deps.py 或 pip install rapidocr_onnxruntime 安装）
"""

from __future__ import annotations

import re

import numpy as np

# OCR 场景只认「主标题级」模式（章/卷/序等），避免把 一、 1. 小节误判成章
_OCR_HEADING_PATTERNS = [
    re.compile(r"^第[0-9０-９一二三四五六七八九十百千万零两]{1,9}[章节回卷部篇集]"),
    re.compile(r"^卷[一二三四五六七八九十百千万零两]{1,4}"),
    re.compile(r"^[【\[]?(?:序章|序言|前言|楔子|引子|尾声|终章|后记|番外|绪论|引言|导论|目录|结语)[】\]]?"),
    re.compile(r"^(?:Chapter|CHAPTER|Chap\.?|Part|PART)\s+[0-9IVXLCDMivxlcdm]+"),
]

# 目录行的特征：以 1~3 位数字结尾（页码）或包含大量点线
_TOC_PAGENUM_RE = re.compile(r"\d{1,3}$")
_DOT_LEADER_RE = re.compile(r"·{2,}|\.{4,}|…{2,}")
_SENT_ENDINGS = ("。", "！", "？", "；", "，", ".", "!", "?", ";", ",", "：", ":")


def _looks_like_heading(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 40:
        return False
    if t.endswith(_SENT_ENDINGS):
        return False
    if _TOC_PAGENUM_RE.search(t):      # 目录行：行尾页码
        return False
    if _DOT_LEADER_RE.search(t):       # 目录行：点线引导符
        return False
    return any(p.search(t) for p in _OCR_HEADING_PATTERNS)


class PdfOcr:
    """惰性初始化 RapidOCR 引擎；每页渲染 → 识别 → 行分类 → 段落化。"""

    def __init__(self, zoom: float = 2.0):
        self._engine = None
        self.zoom = zoom
        self.unavailable: str | None = None

    def ensure_engine(self):
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                self.unavailable = (
                    "未安装 OCR 依赖（rapidocr_onnxruntime / onnxruntime）。"
                    "请运行: python tools/fetch_deps.py，或 pip install rapidocr_onnxruntime")
                raise RuntimeError(self.unavailable) from exc
            self._engine = RapidOCR()
        return self._engine

    def page_blocks(self, page) -> list[tuple[str, str]]:
        """识别一页，返回 [(kind, text), ...]，kind ∈ {'heading','para'}（按阅读顺序）。

        标题识别基于单行文本（短行 + 章节正则 + 排除目录行特征）。
        段落识别：行距明显增大 → 新段；**行首缩进**（x0 明显大于左边界，中文
        书籍段落缩进两字）→ 新段，避免段落被误合并成“挤在一起”的长段。
        """
        engine = self.ensure_engine()
        import pymupdf as fitz

        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n)
        result, _ = engine(arr)
        if not result:
            return []

        lines: list[tuple[float, float, float, str]] = []
        for box, text, _score in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append((min(xs), min(ys), max(ys), text.strip()))
        lines.sort(key=lambda l: (l[1], l[0]))

        # 左边界 = 页面上最小 x0；缩进阈值 ≈ 1.2 倍行高（两字缩进）
        left_margin = min(l[0] for l in lines)
        heights = [l[2] - l[1] for l in lines if l[2] > l[1]]
        median_h = sorted(heights)[len(heights) // 2] if heights else 24.0
        indent_th = max(median_h * 1.2, 16.0)

        items: list[tuple[str, str]] = []
        cur: list[str] = []
        prev_bottom: float | None = None
        prev_height = 0.0
        for x0, y0, y1, text in lines:
            if not text:
                continue
            height = y1 - y0
            new_para = prev_bottom is not None and (
                (y0 - prev_bottom) > max(height, prev_height) * 1.4   # 行距增大
                or (x0 - left_margin) > indent_th                       # 行首缩进
            )
            if new_para:
                _flush_para(items, cur)
            # 单行标题优先（独立成 heading 块）
            if _looks_like_heading(text):
                _flush_para(items, cur)
                items.append(("heading", text))
                prev_bottom = y1
                prev_height = height
                continue
            cur.append(text)
            prev_bottom = y1
            prev_height = height
        _flush_para(items, cur)
        return items


def _flush_para(items: list[tuple[str, str]], cur: list[str]):
    if cur:
        text = "".join(t for t in cur if t).strip()
        if text:
            items.append(("para", text))
        cur.clear()
