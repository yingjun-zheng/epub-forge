# -*- coding: utf-8 -*-
"""数据模型：块 / 章节 / 解析后的文档。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Block:
    """文档的最小结构单元。kind: heading | para | image | hr | pre"""

    kind: str
    text: str = ""            # 纯文本（标题、段落、图片说明）
    html: str = ""            # 已渲染的 HTML 片段（para/pre 用；为空则构建时用 text 转义生成）
    level: int = 0            # 标题级别 1..6
    src: str = ""             # 图片来源（本地路径或 data URI）
    alt: str = ""             # 图片 alt

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        head = self.text[:24].replace("\n", " ")
        return f"<Block {self.kind} lv={self.level} {head!r}>"


@dataclass
class Chapter:
    """一个 EPUB 章节：标题 + 内容块列表。"""

    title: str
    blocks: list[Block] = field(default_factory=list)

    @property
    def text_len(self) -> int:
        return sum(len(b.text) for b in self.blocks if b.kind in ("para", "pre"))

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    def merge(self, other: "Chapter") -> None:
        """把 other 的内容并入本章（标题保留，追加一块分隔）。"""
        self.blocks.append(Block(kind="hr"))
        self.blocks.extend(other.blocks)


@dataclass
class ParsedDocument:
    """解析后的源文档（未分章，或已带结构标题）。"""

    source_path: str
    fmt: str                  # txt | md | html | docx | pdf
    title: str = ""           # 自动推断的书名
    blocks: list[Block] = field(default_factory=list)
    images: dict[str, bytes] = field(default_factory=dict)  # 嵌入文件名 → 字节
    warnings: list[str] = field(default_factory=list)

    @property
    def total_text_len(self) -> int:
        return sum(len(b.text) for b in self.blocks)

    @property
    def heading_count(self) -> int:
        return sum(1 for b in self.blocks if b.kind == "heading")
