# -*- coding: utf-8 -*-
"""自动分章引擎。

流程: ParsedDocument(blocks) → segment() → list[Chapter]

分章策略（检测模式）:
  * auto     —— 优先用结构标题（MD/HTML/DOCX 样式/PDF 书签）；不够则用正则探测纯文本标题；
                再不够则按篇幅切分。
  * heading  —— 只用结构标题（含级别上限），不够则按篇幅兜底。
  * regex    —— 用户自定义正则匹配标题行。
  * size     —— 纯按篇幅切分。
"""

from __future__ import annotations

import re
import statistics

from .blocks import Block, Chapter, ParsedDocument

# 常见中文/英文章节标题正则（用于纯文本探测，章级）
TEXT_HEADING_PATTERNS = [
    re.compile(r"^第[0-9０-９一二三四五六七八九十百千万零两]{1,9}[章节回篇集]"),
    re.compile(r"^[【\[]?(?:序章|序言|前言|楔子|引子|尾声|终章|后记|番外|绪论|引言|导论|目录|结语)[】\]]?"),
    re.compile(r"^(?:Chapter|CHAPTER|Chap\.?)\s+[0-9IVXLCDMivxlcdm]+"),
    re.compile(r"^[一二三四五六七八九十]{1,4}[、．.]\s*\S"),
    re.compile(r"^[0-9]{1,4}[\.、．]\s*\S"),
    re.compile(r"^[A-Z][A-Z0-9\s&'\-—·]{3,}$"),  # 全大写短行
]

# 卷/部级标题正则（第一卷 / 卷二 / 第三部 / Volume 1 / Part 2 等）
VOLUME_PATTERNS = [
    re.compile(r"^第[0-9０-９一二三四五六七八九十百千万零两]{1,9}[卷部]"),
    re.compile(r"^卷[一二三四五六七八九十百千万零两]{1,4}"),
    re.compile(r"^(?:volume|vol\.?|book|part)\s+[0-9IVXLCDMivxlcdm]+", re.IGNORECASE),
]

# 排除句子结尾标点的"标题嫌疑"检测
_SENT_END = ("。", "！", "？", "；", "，", ".", "!", "?", ";", ",", "：", ":")

# 强标题前缀: 行以「第X章/卷/部」「番外」等开头时, 标题置信度高。
# 「章/卷」后必须跟分隔符(空白/标点/行尾), 防「第一章讲的是往事。」
# 这类以"第X章"开头的正文句子误判; 番外/楔子等条目同样要求后跟
# 数字/标题性后缀(篇集传录志记之上中下)或分隔符 —— 否则「番外正文。」
# 会被当标题, 标题块不进章节内容导致正文丢失。
_SPECIAL_TITLE_WORDS = r"序章|序言|前言|楔子|引子|尾声|终章|后记|番外|绪论|引言|导论|目录|结语"
_STRONG_TITLE_PREFIX = re.compile(
    r"^(?:第[0-9０-９一二三四五六七八九十百千万零两]{1,9}[章节回篇集卷部]"
    r"(?=$|\s|[：:·、，,.。;；!！?？—\-（）()【】\[\]「」『』《》\"'])"
    rf"|[【\[]?(?:{_SPECIAL_TITLE_WORDS})(?=$|\s|[0-9０-９一二三四五六七八九十百]"
    r"|篇|集|传|录|志|记|之|上|中|下|[：:·、，,.。;；!！?？—\-（）()【】\[\]「」『』《》\"'])"
    r"|卷[一二三四五六七八九十百千万零两]{1,4}"
    r"|(?:Chapter|CHAPTER|Chap\.?)\s+[0-9IVXLCDMivxlcdm]+)"
)

MAX_TITLE_LEN = 48


class SegmentOptions:
    """分章参数。"""

    def __init__(self, mode: str = "auto", max_level: int = 1,
                 custom_regex: str = "", paras_per_chunk: int = 8,
                 min_chars: int = 500, no_split: bool = False):
        self.mode = mode            # auto | heading | regex | size
        self.max_level = max_level  # 0 = 不限级别
        self.custom_regex = custom_regex
        self.paras_per_chunk = paras_per_chunk
        self.min_chars = min_chars
        self.no_split = no_split    # True = 整本作为一章，不执行分章

    def __repr__(self) -> str:  # pragma: no cover
        return (f"SegmentOptions(mode={self.mode}, max_level={self.max_level}, "
                f"paras={self.paras_per_chunk}, min_chars={self.min_chars}, "
                f"no_split={self.no_split})")


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------

def segment(doc: ParsedDocument, opts: SegmentOptions | None = None) -> tuple[list[Chapter], list[str]]:
    opts = opts or SegmentOptions()
    notes: list[str] = []
    blocks = doc.blocks
    if not blocks:
        return [], ["源文档为空，没有可转换的内容。"]

    # 不分章：整本作为一章
    if opts.no_split:
        title = doc.title or "正文"
        return [Chapter(title, list(blocks))], ["已选择「不分章」，整本作为一章。"]

    starts: list[int] = []

    if opts.mode == "size":
        chapters = _split_by_size(blocks, opts)
        notes.append(f"按篇幅切分为 {len(chapters)} 章（每章约 {opts.paras_per_chunk} 段）。")
        return _post_process(chapters), notes

    if opts.mode == "regex":
        if not opts.custom_regex:
            notes.append("自定义正则为空，回退为自动检测。")
            return segment(doc, SegmentOptions(mode="auto", max_level=opts.max_level,
                                               paras_per_chunk=opts.paras_per_chunk,
                                               min_chars=opts.min_chars))
        try:
            pat = re.compile(opts.custom_regex)
        except re.error as exc:
            notes.append(f"正则无效({exc})，回退为自动检测。")
            return segment(doc, SegmentOptions(mode="auto", max_level=opts.max_level,
                                               paras_per_chunk=opts.paras_per_chunk,
                                               min_chars=opts.min_chars))
        starts = [i for i, b in enumerate(blocks)
                  if b.kind in ("para", "heading") and pat.search(b.text)]
        if not starts:
            notes.append("自定义正则未匹配到任何行，回退为按篇幅切分。")
            chapters = _split_by_size(blocks, opts)
            return _post_process(chapters), notes
        notes.append(f"自定义正则匹配到 {len(starts)} 个章节起点。")

    else:  # auto | heading
        # 1) 结构标题
        starts = [i for i, b in enumerate(blocks)
                  if b.kind == "heading" and (opts.max_level == 0 or b.level <= opts.max_level)]
        if starts:
            notes.append(f"按结构标题识别到 {len(starts)} 个章节起点。")
        if opts.mode == "auto" and len(starts) < 2:
            # 2) 纯文本正则探测
            text_starts = _detect_text_headings(blocks)
            if len(text_starts) > len(starts):
                notes.append(f"结构标题不足，改用纯文本标题探测（{len(text_starts)} 个）。")
                starts = text_starts
            elif text_starts:
                notes.append(f"结构标题 {len(starts)} 个，另探测到 {len(text_starts)} 个文本标题，采用较多者。")
                starts = text_starts if len(text_starts) >= 2 else starts
        if opts.mode == "heading" and len(starts) < 2:
            notes.append("结构标题不足 2 个，按篇幅兜底切分。")
            chapters = _split_by_size(blocks, opts)
            return _post_process(chapters), notes

    # 卷/部探测（第一卷/第三部/卷二 等，章正则已排除卷部字符，互不干扰）
    volume_starts: list[int] = []
    if opts.mode in ("auto", "heading"):
        volume_starts = _detect_text_headings(blocks, VOLUME_PATTERNS)

    if not starts and not volume_starts:
        notes.append("未识别到章节标题，按篇幅切分。")
        chapters = _split_by_size(blocks, opts)
        return _post_process(chapters), notes

    if len(volume_starts) >= 2:
        # 两级结构：卷/部作分组，章挂到所属卷，目录按卷嵌套
        notes.append(f"识别到 {len(volume_starts)} 个卷/部标题、{len(starts)} 个章节标题，按两级结构切分。")
        chapters = _cut_at_two_level(blocks, starts, volume_starts, doc.title)
        return _post_process(chapters), notes

    if not starts and volume_starts:
        # 仅卷无章（或只有单个卷标题）：卷起点充当章起点，单级切分
        notes.append(f"未识别到更低层级章标题，按 {len(volume_starts)} 个卷/部标题切分。")
        chapters = _cut_at(blocks, volume_starts, doc.title)
        return _post_process(chapters), notes

    if volume_starts:
        # 单个卷标题 + 章标题：并入章起点一起切（兼容旧的平铺行为）
        starts = sorted(set(starts) | set(volume_starts))

    chapters = _cut_at(blocks, starts, doc.title)
    return _post_process(chapters), notes


# --------------------------------------------------------------------------
# 切分实现
# --------------------------------------------------------------------------

def _cut_at(blocks: list[Block], starts: list[int], doc_title: str) -> list[Chapter]:
    """在 starts 指定的标题块处切分。标题块本身不进入章节内容（由章节标题承担）。"""
    chapters: list[Chapter] = []
    if starts[0] > 0:
        pre = blocks[: starts[0]]
        chapters.append(Chapter(doc_title or "前言", pre))
    for k, idx in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(blocks)
        title = blocks[idx].text.strip() or f"第{k + 1}章"
        chapters.append(Chapter(title, list(blocks[idx + 1: end])))
    return chapters


def _cut_at_two_level(blocks: list[Block], ch_starts: list[int], vol_starts: list[int],
                      doc_title: str) -> list[Chapter]:
    """两级切分：卷/部标题作分组（Chapter.volume），章标题切章。

    * 卷标题块之后、下一章起点之前的正文 → 卷首章（标题用卷名，volume 同名）；
    * 章起点处的章挂到当前卷；卷名之前出现的章 volume 为空（如开篇的序章）。
    """
    vol_titles = {i: blocks[i].text.strip() for i in vol_starts}
    marks = sorted([(i, "vol" if i in vol_titles else "ch")
                    for i in set(ch_starts) | set(vol_starts)])
    chapters: list[Chapter] = []
    if marks[0][0] > 0:
        chapters.append(Chapter(doc_title or "前言", list(blocks[: marks[0][0]])))
    cur_volume = ""
    for k, (idx, kind) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(blocks)
        body = list(blocks[idx + 1: end])
        if kind == "vol":
            cur_volume = vol_titles[idx] or f"第{k + 1}卷"
            if body:
                # 卷名与首章之间的内容 → 卷首章（常见于卷引言/卷首语）
                chapters.append(Chapter(cur_volume, body, volume=cur_volume))
        else:
            title = blocks[idx].text.strip() or f"第{k + 1}章"
            chapters.append(Chapter(title, body, volume=cur_volume))
    return chapters


def _detect_text_headings(blocks: list[Block], patterns: list[re.Pattern] | None = None) -> list[int]:
    """在纯文本段落里用正则探测标题行。返回命中块的索引（升序）。

    patterns 缺省用章级标题正则；探测卷/部级标题时传 VOLUME_PATTERNS。
    """
    patterns = patterns if patterns is not None else TEXT_HEADING_PATTERNS
    hits: list[int] = []
    for i, b in enumerate(blocks):
        if b.kind not in ("para", "heading"):
            continue
        line = b.text.strip()
        if not line or "\n" in line:
            continue  # 只探测单行
        if len(line) > MAX_TITLE_LEN:
            continue
        if line.endswith(_SENT_END):
            # 网文标题行尾带句号很常见（「第一章 往事回忆。」）——
            # 强前缀标题且行尾是句号时放行（逗号/问号等结尾仍视为正文）。
            # 放行需同时满足: 短行(≤24字)且行内无逗号 —— 否则「卷标题+卷引言」
            # 粘连的长句（「第一部 xxx 始于乱世，群雄并起，…。」）会误判为标题。
            if not (line.endswith(("。", "."))
                    and len(line) <= 24
                    and "，" not in line and "," not in line
                    and _STRONG_TITLE_PREFIX.match(line)):
                continue
        if any(p.search(line) for p in patterns):
            hits.append(i)
    # 去重：连续命中且文本相同只保留第一个
    dedup: list[int] = []
    prev = None
    for i in hits:
        if blocks[i].text.strip() != prev:
            dedup.append(i)
            prev = blocks[i].text.strip()
    return dedup


def _split_by_size(blocks: list[Block], opts: SegmentOptions) -> list[Chapter]:
    content = [b for b in blocks if b.kind in ("para", "pre", "image", "hr")]
    if not content:
        return [Chapter("正文", list(blocks))]
    total = sum(len(b.text) for b in content if b.kind in ("para", "pre"))
    if total < opts.min_chars:
        return [Chapter("正文", list(blocks))]
    paras = opts.paras_per_chunk or 8
    chunks: list[list[Block]] = []
    cur: list[Block] = []
    for b in content:
        cur.append(b)
        if len(cur) >= paras:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return [Chapter(f"第{i + 1}章", ch) for i, ch in enumerate(chunks)]


def _post_process(chapters: list[Chapter]) -> list[Chapter]:
    """清理：丢弃空章节（标题无内容，含空的「前言」占位章）。"""
    out: list[Chapter] = []
    for ch in chapters:
        if not ch.blocks and out:
            continue  # 空章节直接丢弃
        out.append(ch)
    if not out and chapters:
        out = chapters
    return out


def chapter_stats(chapters: list[Chapter]) -> tuple[int, int]:
    """返回 (总章数, 总字数)。"""
    total = sum(c.text_len for c in chapters)
    return len(chapters), total
