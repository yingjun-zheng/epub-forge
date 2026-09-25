# -*- coding: utf-8 -*-
"""EPUB3 生成器（基于 ebooklib）。

输入: list[Chapter] + BookMeta + 图片 + 封面
输出: .epub 文件
"""

from __future__ import annotations

import mimetypes
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .blocks import Block, Chapter
from .utils import escape_html

STYLE_CSS = """\
@namespace epub "http://www.idpf.org/2007/ops";
body { font-family: "Noto Serif CJK SC", "Source Han Serif SC", "SimSun", serif;
       line-height: 1.9; margin: 5% 6%; text-align: justify;
       -epub-hyphens: none; hyphens: none; }
h1.chapter-title { font-size: 1.5em; text-align: center; margin: 0 0 1.8em;
                   font-weight: bold; line-height: 1.5; }
h1, h2, h3, h4, h5, h6 { font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
                         margin: 1.6em 0 0.9em; line-height: 1.45;
                         text-align: left; text-indent: 0; }
p { margin: 0 0 0.9em 0; text-indent: 2em; }
p.para { margin: 0 0 0.9em 0; line-height: 1.9; text-indent: 2em; }
p.noindent, li p, blockquote p { text-indent: 0; }
blockquote { margin: 0.9em 1.5em; color: #555; border-left: 3px solid #ccc; padding-left: 1em; }
pre { font-family: Consolas, monospace; font-size: 0.85em; background: #f6f6f6;
      padding: 0.9em; white-space: pre-wrap; margin: 0.9em 0; line-height: 1.5; }
hr { border: none; border-top: 1px solid #ccc; margin: 1.8em 4em; }
img { max-width: 100%; height: auto; }
figure { margin: 1em auto; text-align: center; }
figcaption { font-size: 0.85em; color: #666; margin-top: 0.4em; }
table { border-collapse: collapse; margin: 0.9em auto; }
td, th { border: 1px solid #999; padding: 0.3em 0.6em; font-size: 0.9em; }
ul, ol { margin: 0.6em 0 0.9em 1.5em; }
li { margin: 0.25em 0; text-indent: 0; }
.copyright { text-align: center; color: #888; font-size: 0.85em; margin-top: 2em; }
"""


@dataclass
class BookMeta:
    """EPUB 元数据。"""

    title: str = "未命名"
    author: str = ""
    lang: str = "zh"
    publisher: str = ""
    description: str = ""
    identifier: str = field(default_factory=lambda: uuid.uuid4().hex)
    date: str = field(default_factory=lambda: date.today().isoformat())


def _media_type(fname: str) -> str:
    mt, _ = mimetypes.guess_type(fname)
    if mt:
        return mt
    ext = fname.rsplit(".", 1)[-1].lower()
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml",
            "bmp": "image/bmp"}.get(ext, "application/octet-stream")


# 段落的内联排版兜底：即使阅读器忽略外部 CSS，也能保证段距/行距/首行缩进
PARA_INLINE_STYLE = "margin:0 0 0.9em 0; line-height:1.9; text-indent:2em;"

_P_WRAP_RE = re.compile(r"^\s*<p[^>]*>(.*)</p>\s*$", re.S)


def _para_inner(b: Block) -> str | None:
    """取段落内容：b.html 若是简单 <p> 包装则抽取内部；否则返回 None（保持原样）。"""
    if b.html:
        m = _P_WRAP_RE.match(b.html)
        if m:
            return m.group(1)
        return None
    return "<br/>".join(escape_html(ln) for ln in b.text.split("\n"))


def render_chapter(ch: Chapter, img_map: dict[str, str]) -> str:
    """章节 → XHTML 字符串。"""
    body: list[str] = []
    body.append(f'<h1 class="chapter-title">{escape_html(ch.title)}</h1>')
    blocks = list(ch.blocks)
    # 跳过与章名重复的起始标题（源文档的 h1 可能既是章名又是正文首块）
    if blocks and blocks[0].kind == "heading" and blocks[0].text.strip() == ch.title.strip():
        blocks = blocks[1:]
    for b in blocks:
        if b.kind == "heading":
            lvl = min(max(b.level or 2, 1), 6)
            body.append(f"<h{lvl}>{escape_html(b.text)}</h{lvl}>")
        elif b.kind == "para":
            inner = _para_inner(b)
            if inner is None:
                body.append(b.html)  # table/pre 等非 <p> 结构保持原样
            else:
                body.append(f'<p class="para" style="{PARA_INLINE_STYLE}">{inner}</p>')
        elif b.kind == "pre":
            body.append(b.html if b.html else "<pre>" + escape_html(b.text) + "</pre>")
        elif b.kind == "hr":
            body.append("<hr/>")
        elif b.kind == "image":
            src = img_map.get(b.src, b.src)
            cap = f"<figcaption>{escape_html(b.alt)}</figcaption>" if b.alt else ""
            body.append(f'<figure><img src="{escape_html(src)}" alt="{escape_html(b.alt)}"/>{cap}</figure>')
    # 注意: 不要输出 <?xml ... encoding=...?> 声明 —— lxml 的 html 解析器
    # 不接受带编码声明的 Unicode 字符串，会导致 ebooklib 解析 body 为空。
    # CSS 链接由 ebooklib 的 item.add_link() 注入（写在这里会被重建时丢弃）。
    return (
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '<head><title>{title}</title></head>\n'
        '<body>\n{body}\n</body></html>'
    ).format(title=escape_html(ch.title), body="\n".join(body))


def build_epub(chapters: list[Chapter], meta: BookMeta, output_path: str | Path,
               images: dict[str, bytes] | None = None,
               cover_bytes: bytes | None = None, cover_name: str = "cover.jpg",
               progress_cb=None) -> str:
    """生成 EPUB3 文件，返回输出路径。progress_cb(percent: float, msg: str)。

    注意（ebooklib 0.20 行为）:
      * spine 必须引用 item 对象（传文件名会被原样写成 idref，导致阅读器
        无法按序渲染正文 —— 表现为“只有目录、翻不了页”）。
      * 章节的 CSS 必须通过 item.add_link() 注入，写在章节 HTML head 里的
        <link> 会被 ebooklib 重建时丢弃。
    """
    from ebooklib import epub

    def prog(pct: float, msg: str):
        if progress_cb:
            progress_cb(pct, msg)

    output_path = Path(output_path)
    book = epub.EpubBook()
    book.set_identifier(meta.identifier or uuid.uuid4().hex)
    book.set_title(meta.title or "未命名")
    book.set_language(meta.lang or "zh")
    if meta.author:
        book.add_author(meta.author)
    if meta.publisher:
        book.add_metadata("DC", "publisher", meta.publisher)
    if meta.description:
        book.add_metadata("DC", "description", meta.description)
    book.add_metadata("DC", "date", meta.date)

    spine: list = []  # 全部用 item 对象

    # 封面（封面页需显式加入 spine，否则多数阅读器不显示）
    if cover_bytes:
        prog(2, "写入封面…")
        book.set_cover(cover_name, cover_bytes, create_page=True)
        cover_item = next((i for i in book.items
                           if getattr(i, "file_name", "").endswith("cover.xhtml")), None)
        if cover_item is not None:
            spine.append(cover_item)

    # 样式
    style = epub.EpubItem(uid="style", file_name="style/main.css",
                          media_type="text/css", content=STYLE_CSS.encode("utf-8"))
    book.add_item(style)

    # 图片
    # 注意: 章节 XHTML 位于 text/ 子目录，正文里的图片引用必须写成
    # ../images/xxx（相对章节文件解析），否则严格阅读器（Calibre 等）
    # 会按 text/images/xxx 寻址而显示不出图片。
    img_map: dict[str, str] = {}
    for fname, data in (images or {}).items():
        safe = fname.replace("/", "_").replace("\\", "_")
        epub_fname = f"images/{safe}"
        book.add_item(epub.EpubImage(uid=f"img-{safe}", file_name=epub_fname,
                                     media_type=_media_type(safe), content=data))
        img_map[fname] = f"../{epub_fname}"

    # 章节
    items: list = []
    total = max(len(chapters), 1)
    for i, ch in enumerate(chapters, 1):
        prog(5 + 80 * i / total, f"生成章节 {i}/{len(chapters)}: {ch.title[:30]}")
        fname = f"text/chap{i:04d}.xhtml"
        item = epub.EpubHtml(title=ch.title, file_name=fname, lang=meta.lang or "zh")
        item.content = render_chapter(ch, img_map)
        item.add_link(href="../style/main.css", rel="stylesheet", type="text/css")
        book.add_item(item)
        items.append(item)
        spine.append(item)

    # 目录：有卷/部结构时按卷嵌套（EPUB3 nav 二级列表 + NCX 嵌套 navPoint），
    # 无卷结构的章节平铺。Section.href 必须指向该卷第一章文件 —— ebooklib
    # 的 NCX 写入器要求 navPoint content src 非空（空 href 会生成非法结构）。
    toc: list = []
    i, n = 0, len(chapters)
    while i < n:
        vol = chapters[i].volume
        if not vol:
            toc.append(items[i])
            i += 1
            continue
        group = []
        while i < n and chapters[i].volume == vol:
            group.append(items[i])
            i += 1
        toc.append((epub.Section(vol, href=group[0].file_name), group))
    book.toc = toc

    # 导航（nav 在封面之后、正文之前）
    nav = epub.EpubNav()
    book.add_item(nav)
    if spine and spine[0].file_name.endswith("cover.xhtml"):
        spine.insert(1, nav)
    else:
        spine.insert(0, nav)

    book.add_item(epub.EpubNcx())
    book.spine = spine

    prog(90, "写入 EPUB 文件…")
    epub.write_epub(str(output_path), book, {})
    prog(100, "完成")
    return str(output_path)
