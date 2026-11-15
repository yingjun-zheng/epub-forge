# -*- coding: utf-8 -*-
"""多格式源文档解析 → ParsedDocument。

支持的格式:
  .txt / .md / .markdown / .html / .htm / .xhtml / .docx / .pdf

设计要点:
  * 所有格式最终归一化为 Block 列表（heading / para / pre / image / hr）。
  * Markdown / HTML 共用同一个 HTML 结构遍历器（markdown 先渲染成 HTML）。
  * DOCX 通过样式名识别标题，并抽取内嵌图片。
  * PDF 优先使用书签大纲(TOC)，否则按字号启发式识别标题。
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from .blocks import Block, ParsedDocument
from .chapter import TEXT_HEADING_PATTERNS as _TITLE_HINT_RE
from .chapter import VOLUME_PATTERNS as _VOLUME_HINT_RE
from .chapter import _detect_text_headings
from .utils import clean_text, escape_html, infer_title_from_filename, read_text_with_fallback

SUPPORTED_EXT = {
    ".txt": "txt", ".md": "md", ".markdown": "md",
    ".html": "html", ".htm": "html", ".xhtml": "html",
    ".docx": "docx", ".pdf": "pdf",
}

_SKIP_TAGS = {"script", "style", "noscript", "head", "meta", "link", "title", "iframe", "svg"}
_CONTAINER_TAGS = {"div", "section", "article", "main", "body", "header", "footer", "aside", "nav", "figure", "ul", "ol"}
_LEAF_TAGS = {"p", "li", "blockquote", "td", "th", "figcaption", "dt", "dd", "address", "pre", "table"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def detect_format(path: str | Path) -> str | None:
    return SUPPORTED_EXT.get(Path(path).suffix.lower())


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def parse_document(path: str | Path, txt_para_mode: str = "auto",
                   ocr: bool = False, progress_cb=None) -> ParsedDocument:
    """按扩展名分派到具体解析器。

    txt_para_mode: TXT 段落识别方式 —— auto（启发式）/ blank（空行分段）/ line（每行一段）
    ocr:           PDF 无文字层时是否启用 OCR 识别（扫描版）
    progress_cb:   可选回调 cb(percent, msg)，用于报告解析进度
    """
    path = Path(path)
    fmt = detect_format(path)
    if fmt is None:
        raise ValueError(f"不支持的格式: {path.suffix}（支持: {', '.join(sorted(SUPPORTED_EXT))}）")
    if fmt in ("txt", "md", "html"):
        text, enc = read_text_with_fallback(path)
    else:
        text, enc = "", ""
    if fmt == "txt":
        return _parse_txt(path, text, txt_para_mode)
    if fmt == "md":
        return _parse_md(path, text)
    if fmt == "html":
        return _parse_html(path, text)
    if fmt == "docx":
        return _parse_docx(path)
    if fmt == "pdf":
        return _parse_pdf(path, ocr=ocr, progress_cb=progress_cb)
    raise ValueError(f"未实现的解析器: {fmt}")


# --------------------------------------------------------------------------
# TXT
# --------------------------------------------------------------------------

_SENT_ENDINGS = ("。", "！", "？", "”", "』", "」", "…", "…", ".", "!", "?",
                 '"', "'", "）", ")", "】", "]", "》", "〉", "；", "，", ";", ",")


def _detect_txt_para_mode(lines: list[str], cleaned: str) -> str:
    """启发式判断 TXT 段落排布。

    逐行排布（每行一个自然段，常见于中文小说）: 大多数行以句末标点结尾且行较短。
    空行分段: 段落之间有空行，段内多行。
    无空行/少空行且行尾标点少: 按行分段兜底——避免把整章并成一大段“文字墙”。
    """
    if len(lines) < 3:
        return "blank"
    end_count = sum(1 for ln in lines if ln.endswith(_SENT_ENDINGS))
    ratio = end_count / len(lines)
    avg_len = sum(len(ln) for ln in lines) / len(lines)
    if ratio >= 0.55 and avg_len <= 80:
        return "line"
    # 空行数量明显偏少（平均每 3 行不足 1 个空行）→ 段落边界只能靠行
    blank_count = max(len(re.split(r"\n[ \t]*\n", cleaned)) - 1, 0)
    if blank_count * 3 < len(lines):
        return "line"
    return "blank"


# 超长段落的安全分行：仅在句末标点处切开，避免“文字墙”
_LONG_PARA_MIN = 1200
_LONG_PARA_CHUNK = 600
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？…”』」])")


def _split_long_paras(blocks: list[Block]) -> list[Block]:
    """把明显被合并的超长段落在句末标点处切开成多个段落（保留原文顺序）。"""
    out: list[Block] = []
    for b in blocks:
        if b.kind == "para" and len(b.text) > _LONG_PARA_MIN:
            pieces = [s for s in _SENT_SPLIT_RE.split(b.text) if s.strip()]
            if len(pieces) > 1:
                groups: list[str] = []
                cur = ""
                for p in pieces:
                    if len(cur) + len(p) > _LONG_PARA_CHUNK and cur:
                        groups.append(cur)
                        cur = p
                    else:
                        cur += p
                if cur:
                    groups.append(cur)
                for g in groups:
                    g = g.strip()
                    if g:
                        out.append(Block(kind="para", text=g))
                continue
        out.append(b)
    return out


def _parse_txt(path: Path, text: str, para_mode: str = "auto") -> ParsedDocument:
    cleaned = clean_text(text)
    lines = [ln.strip() for ln in cleaned.split("\n") if ln.strip()]
    mode = para_mode
    if mode == "auto":
        mode = _detect_txt_para_mode(lines, cleaned)

    blocks: list[Block] = []
    if mode == "line":
        # 每行视为一个自然段（保留行内软空格）
        for ln in lines:
            blocks.append(Block(kind="para", text=re.sub(r"[ \t]+", " ", ln)))
    else:
        # 空行分段：保留嵌在连续正文中的独立章节标题行。
        for raw in re.split(r"\n[ \t]*\n", cleaned):
            pending: list[str] = []
            for line in (ln.strip() for ln in raw.split("\n")):
                if not line:
                    continue
                candidate = Block(kind="para", text=line)
                is_heading = bool(_detect_text_headings([candidate]) or
                                  _detect_text_headings([candidate], _VOLUME_HINT_RE))
                if is_heading:
                    if pending:
                        blocks.append(Block(kind="para", text=" ".join(pending)))
                        pending = []
                    blocks.append(candidate)
                else:
                    pending.append(line)
            if pending:
                blocks.append(Block(kind="para", text=" ".join(pending)))

    # 超长段落自动在句末分行（识别“顶行/无空行”合并出的文字墙）
    blocks = _split_long_paras(blocks)

    title = infer_title_from_filename(path)
    # 首段若为短单行且非句子 → 视为书名（如「雾隐山庄」）；
    # 命中章节/卷部标题正则的行（如「第一卷 风云初起」）不是书名
    if blocks and len(blocks) >= 3:
        first = blocks[0].text.strip()
        if (len(first) <= 24 and "\n" not in first
                and not first.endswith(_SENT_ENDINGS)
                and not any(p.search(first) for p in _TITLE_HINT_RE)
                and not any(p.search(first) for p in _VOLUME_HINT_RE)):
            title = first
            blocks.pop(0)
    doc = ParsedDocument(source_path=str(path), fmt="txt", title=title, blocks=blocks)
    if mode == "line":
        doc.warnings.append(f"检测到逐行排布，已按每行一段解析（共 {len(blocks)} 段）。")
    if not blocks:
        doc.warnings.append("未解析到任何正文内容。")
    else:
        _integrity_check(doc, text)
    return doc


def _integrity_check(doc: ParsedDocument, source_text: str, source_chars: int | None = None):
    """内容完整性自检：解析所得字数明显少于源文字数时告警（提示可能丢内容）。"""
    if source_chars is None:
        source_chars = len(re.sub(r"\s+", "", source_text))
    parsed = doc.total_text_len
    if source_chars > 200 and parsed < source_chars * 0.9:
        doc.warnings.append(
            f"内容完整性提示：源文档约 {source_chars} 字，解析得到 {parsed} 字，"
            f"疑似丢失 {source_chars - parsed} 字。请检查源文件编码与结构。")


# --------------------------------------------------------------------------
# Markdown / HTML（共用 HTML 遍历器）
# --------------------------------------------------------------------------

def _parse_md(path: Path, text: str) -> ParsedDocument:
    try:
        import markdown as md_lib
        html_str = md_lib.markdown(text, extensions=["extra", "sane_lists", "nl2br"])
    except Exception:  # markdown 库不可用时退化为纯文本
        html_str = "<p>" + escape_html(clean_text(text)).replace("\n", "<br/>") + "</p>"
    blocks, title = _walk_html(html_str, base_dir=path.parent)
    doc = ParsedDocument(source_path=str(path), fmt="md",
                         title=title or infer_title_from_filename(path), blocks=blocks)
    _extract_images(doc.blocks, path.parent, doc)
    return doc


def _parse_html(path: Path, text: str) -> ParsedDocument:
    blocks, title = _walk_html(text, base_dir=path.parent)
    doc = ParsedDocument(source_path=str(path), fmt="html",
                         title=title or infer_title_from_filename(path), blocks=blocks)
    _extract_images(doc.blocks, path.parent, doc)
    return doc


def _walk_html(html_str: str, base_dir: Path) -> tuple[list[Block], str]:
    """遍历 HTML 结构 → blocks。返回 (blocks, 推断标题)。

    关键点: 裸文本（未用 <p>/<div> 包裹、直接写在 <body> 下或混在容器里的
    文字）也会被收集成段落，避免内容丢失（如文末的「全书完」）。
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_str, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    blocks: list[Block] = []

    def walk(el) -> None:
        nonlocal title
        text_buf: list[str] = []

        def flush_text():
            """把缓冲的裸文本吐成一个段落块。"""
            text = " ".join(t.strip() for t in text_buf if t.strip())
            if text.strip():
                blocks.append(Block(kind="para", text=text.strip()))
            text_buf.clear()

        for child in getattr(el, "children", ()):
            if not getattr(child, "name", None):
                # 裸文本节点：先缓冲，遇到下一个元素时再成段
                t = str(child)
                if t.strip():
                    text_buf.append(t)
                continue
            flush_text()
            name = child.name.lower()
            if name in _SKIP_TAGS:
                continue
            if name in _HEADING_TAGS:
                text = child.get_text(" ", strip=True)
                if not text:
                    continue
                blocks.append(Block(kind="heading", text=text, level=int(name[1])))
                if not title and name == "h1":
                    title = text
            elif name == "hr":
                blocks.append(Block(kind="hr"))
            elif name == "img":
                src = child.get("src") or child.get("data-src") or ""
                blocks.append(Block(kind="image", src=src, alt=child.get("alt", "") or ""))
            elif name in _LEAF_TAGS:
                # 段落内嵌图片 → 提升为独立 image 块
                imgs = child.find_all("img") if hasattr(child, "find_all") else []
                for img in imgs:
                    img.extract()
                    blocks.append(Block(kind="image", src=img.get("src") or img.get("data-src") or "",
                                        alt=img.get("alt", "") or ""))
                text = child.get_text(" ", strip=True)
                if not text and name != "pre" and not imgs:
                    continue
                if name == "pre":
                    blocks.append(Block(kind="pre", text=child.get_text(),
                                        html=f"<pre>{child.decode_contents()}</pre>"))
                elif name == "table":
                    blocks.append(Block(kind="pre", text=text,
                                        html=f"<div>{child.decode_contents()}</div>"))
                elif name == "li":
                    blocks.append(Block(kind="para", text=text,
                                        html=f"<p>• {child.decode_contents()}</p>"))
                else:
                    blocks.append(Block(kind="para", text=text,
                                        html=f"<p>{child.decode_contents()}</p>"))
            elif name in _CONTAINER_TAGS:
                has_block_child = any(
                    getattr(c, "name", None) and c.name.lower()
                    in _HEADING_TAGS | _LEAF_TAGS | {"hr", "img"} | _CONTAINER_TAGS
                    for c in child.children
                )
                if has_block_child:
                    walk(child)
                else:
                    text = child.get_text(" ", strip=True)
                    if text.strip():
                        blocks.append(Block(kind="para", text=text,
                                            html=f"<p>{child.decode_contents()}</p>"))
            else:
                text = child.get_text(" ", strip=True)
                if text.strip():
                    blocks.append(Block(kind="para", text=text,
                                        html=f"<p>{child.decode_contents()}</p>"))
        flush_text()

    walk(soup.body or soup)
    return blocks, title


def _extract_images(blocks: list[Block], base_dir: Path, doc: ParsedDocument):
    """把 image 块的 src 解析成字节，登记到 doc.images；失败则移除该块并告警。

    兼容: 本地相对/绝对路径、data: URI。网络图片跳过并告警。
    """
    images: dict[str, bytes] = doc.images
    kept: list[Block] = []
    for b in blocks:
        if b.kind != "image":
            kept.append(b)
            continue
        src = b.src
        try:
            if src.startswith("data:"):
                meta, _, b64 = src.partition(",")
                mime = meta.split(";")[0].split(":")[1]
                data = base64.b64decode(b64)
                ext = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif",
                       "image/webp": "webp", "image/svg+xml": "svg"}.get(mime, "png")
            elif src.startswith(("http://", "https://")):
                doc.warnings.append(f"跳过网络图片: {src[:60]}（请先下载到本地）")
                continue
            else:
                p = Path(src)
                if not p.is_absolute():
                    p = base_dir / p
                data = p.read_bytes()
                ext = p.suffix.lstrip(".").lower() or "png"
            fname = f"img-{len(images) + 1:03d}.{ext}"
            images[fname] = data
            b.src = fname
            kept.append(b)
        except Exception as exc:
            doc.warnings.append(f"图片读取失败 {src[:60]}: {exc}")
            continue
    blocks[:] = kept


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------

_HEADING_STYLE_RE = re.compile(r"^(?:Heading|标题|Title|文档标题)\s*(\d)?$", re.IGNORECASE)


def _parse_docx(path: Path) -> ParsedDocument:
    import docx  # python-docx

    d = docx.Document(str(path))
    blocks: list[Block] = []
    title = ""
    images: dict[str, bytes] = {}
    for p in d.paragraphs:
        # 段落内嵌图片 → 按文档顺序生成 image 块（多图各一块，置于段落文本之前）
        for fname in _docx_para_images(p, images):
            blocks.append(Block(kind="image", src=fname))
        style = (p.style.name or "") if p.style else ""
        text = p.text.strip()
        m = _HEADING_STYLE_RE.match(style)
        if m:
            level = int(m.group(1)) if m.group(1) else 1
            if text:
                blocks.append(Block(kind="heading", text=text, level=level))
                if not title and level == 1:
                    title = text
            continue
        if not text:
            continue
        # 表格行内段落去重
        blocks.append(Block(kind="para", text=text))

    # 表格 → 文本行
    for t in d.tables:
        rows = [" | ".join(c.text.strip() for c in row.cells) for row in t.rows]
        if rows:
            joined = "\n".join(rows)
            blocks.append(Block(kind="pre", text=joined,
                                html="<p>" + escape_html(joined).replace("\n", "<br/>") + "</p>"))

    doc = ParsedDocument(source_path=str(path), fmt="docx",
                         title=title or infer_title_from_filename(path), blocks=blocks)
    doc.images = images
    # 内容完整性自检
    src_chars = sum(len(p.text) for p in d.paragraphs)
    src_chars += sum(len(c.text) for t in d.tables for row in t.rows for c in row.cells)
    if src_chars > 200:
        _integrity_check(doc, "", source_chars=src_chars)
    return doc


def _docx_para_images(p, images: dict[str, bytes]) -> list[str]:
    """抽取单个段落里的内嵌图片，登记到 images，返回按顺序的文件名列表。

    通过段落 XML 里的 a:blip/@r:embed 定位关系 ID，保证图片出现在正文
    对应位置（此前只收集 blob 不记位置，导致图片永远不出现在正文中）。
    """
    out: list[str] = []
    try:
        rids = p._p.xpath(".//a:blip/@r:embed")
    except Exception:
        return out
    for rid in rids:
        try:
            part = p.part.related_parts[rid]
        except (KeyError, AttributeError):
            continue
        try:
            ext = Path(str(part.partname)).suffix.lstrip(".").lower() or "png"
            fname = f"img-{len(images) + 1:03d}.{ext}"
            images[fname] = part.blob
            out.append(fname)
        except Exception:
            continue
    return out


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def _parse_pdf(path: Path, ocr: bool = False, progress_cb=None) -> ParsedDocument:
    try:
        import pymupdf as fitz  # PyMuPDF 新包名
    except ImportError:
        import fitz  # 旧名兼容

    from .ocr import PdfOcr

    pdf = fitz.open(str(path))
    try:
        meta = pdf.metadata or {}
        title = (meta.get("title") or "").strip() or infer_title_from_filename(path)
        toc = pdf.get_toc()  # [[level, title, page], ...]
        toc = _filter_toc_page_numbers(toc)
        warnings: list[str] = []
        blocks: list[Block] = []

        ocr_engine = PdfOcr() if ocr else None
        ocr_pages: list[int] = []
        total_text_chars = 0

        # 每页内容: list[(kind, text)]，kind ∈ {'heading','para'}；以及行级字号信息
        pages_content: list[list[tuple[str, str]]] = []
        pages_sizes: list[list[tuple[str, float]]] = []
        page_count = pdf.page_count
        for pno in range(page_count):
            page = pdf[pno]
            text_blocks = [b[4].strip() for b in page.get_text("blocks") if b[6] == 0]
            text_blocks = [b for b in text_blocks if b]
            total_text_chars += sum(len(b) for b in text_blocks)

            # 无文字层且启用 OCR → 识别该页（含单行标题分类）
            if not text_blocks and ocr_engine is not None:
                if progress_cb:
                    progress_cb(min(60.0, 5 + (pno + 1) * 55 / max(page_count, 1)),
                                f"OCR 识别第 {pno + 1}/{page_count} 页…")
                try:
                    items = ocr_engine.page_blocks(page)
                    if items:
                        pages_content.append(items)
                        ocr_pages.append(pno + 1)
                    else:
                        pages_content.append([])
                except RuntimeError as exc:
                    warnings.append(str(exc))
                    ocr_engine = None  # 引擎不可用则放弃后续 OCR
                    pages_content.append([])
            else:
                pages_content.append([("para", tb) for tb in text_blocks])

            lines = []
            for b in page.get_text("dict").get("blocks", []):
                if b.get("type") != 0:
                    continue
                for line in b.get("lines", []):
                    text = "".join(sp.get("text", "") for sp in line.get("spans", []))
                    size = max((sp.get("size", 0) for sp in line.get("spans", [])), default=0)
                    if text.strip():
                        lines.append((text.strip(), size))
            pages_sizes.append(lines)

        def emit_page(pno: int):
            for kind, text in pages_content[pno]:
                if kind == "heading":
                    blocks.append(Block(kind="heading", text=text, level=1))
                else:
                    blocks.append(Block(kind="para", text=text))

        if toc:
            # 大纲驱动: 标题插到对应页开头
            per_page: dict[int, list[tuple[int, str]]] = {}
            for lvl, t, pg in toc:
                if 1 <= pg <= page_count:
                    per_page.setdefault(pg, []).append((lvl, t))
            for pno in range(page_count):
                for lvl, t in per_page.get(pno + 1, []):
                    blocks.append(Block(kind="heading", text=t, level=min(lvl, 6)))
                emit_page(pno)
            warnings.append(f"已使用 PDF 书签大纲识别章节（{len(toc)} 条）。")
        else:
            # 字号启发式: 明显大于正文主字号的短行 → 标题
            headings = _detect_pdf_headings(pages_sizes)
            head_by_page: dict[int, list[str]] = {}
            for pno, t in headings:
                head_by_page.setdefault(pno, []).append(t)
            for pno in range(page_count):
                for t in head_by_page.get(pno, []):
                    blocks.append(Block(kind="heading", text=t, level=1))
                emit_page(pno)
            if headings:
                warnings.append(f"PDF 无书签，按字号启发式识别到 {len(headings)} 个疑似标题。")
            else:
                warnings.append("PDF 无书签且未识别到标题，将按篇幅自动分章。")

        # 扫描版提示（无文字层）
        if ocr_pages:
            warnings.append(f"扫描版 PDF：{len(ocr_pages)}/{page_count} 页无文字层，已通过 OCR 识别。")
        elif total_text_chars == 0:
            if ocr_engine is None and ocr:
                warnings.append("OCR 引擎不可用，未识别扫描页。请安装 rapidocr_onnxruntime 后重试。")
            else:
                warnings.append(
                    "该 PDF 无文字层（扫描版），未提取到正文。"
                    "请在 GUI 勾选「扫描版自动 OCR」或 CLI 加 --ocr 进行识别。")

        # 超长段落自动在句末分行（PDF 文本块偶尔会合并成大段）
        blocks = _split_long_paras(blocks)

        doc = ParsedDocument(source_path=str(path), fmt="pdf", title=title,
                             blocks=blocks, warnings=warnings)
        # 内容完整性自检：blocks 模式提取的文字 vs text 模式
        src_chars = sum(len(pdf[p].get_text("text")) for p in range(page_count))
        if src_chars > 200:
            _integrity_check(doc, "", source_chars=src_chars)
        return doc
    finally:
        pdf.close()


_TOC_PAGENUM_RE = re.compile(r"^\s*\d{1,4}\s*$")


def _filter_toc_page_numbers(toc: list) -> list:
    """过滤 FreePic2Pdf 等工具生成的「纯页码」书签（如 1..247），保留真实章节名。"""
    if not toc:
        return toc
    digits = [t for t in toc if _TOC_PAGENUM_RE.match(t[1] or "")]
    if digits and len(digits) / len(toc) > 0.5:
        return [t for t in toc if not _TOC_PAGENUM_RE.match(t[1] or "")]
    return toc


def _detect_pdf_headings(pages_sizes: list[list[tuple[str, float]]]) -> list[tuple[int, str]]:
    from collections import Counter

    # 正文字号 = 出现次数最多的字号（并列取较小者）；标题必须明显更大
    cnt = Counter(round(sz, 1) for page in pages_sizes for _, sz in page if sz > 0)
    if not cnt:
        return []
    body_size = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    threshold = body_size * 1.35
    out: list[tuple[int, str]] = []
    for pno, lines in enumerate(pages_sizes):
        for text, sz in lines:
            t = text.strip()
            if (sz >= threshold and 0 < len(t) <= 60
                    and not t.endswith(("。", "！", "？", "；", ".", "!", "?"))):
                out.append((pno, t))
    return out
