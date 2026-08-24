# -*- coding: utf-8 -*-
"""裸文本 / 完整性自检验证。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS = os.path.join(ROOT, ".deps")
if os.path.isdir(DEPS):
    sys.path.insert(0, DEPS)

from epubforge.sources import parse_document  # noqa: E402
from epubforge.chapter import SegmentOptions, segment  # noqa: E402
from epubforge.builder import BookMeta, build_epub  # noqa: E402

OUT = os.path.join(ROOT, "test_out")
os.makedirs(OUT, exist_ok=True)

html = """<!DOCTYPE html>
<html><head><title>裸文本测试</title></head>
<body>
第一章 裸文本测试
<p>这是第一段，有标签包裹。</p>
文末游离文字：这是直接写在 body 下的裸文本，没有 p 标签。
<div>容器里只有文本，没有子块元素。</div>
<div>混合容器：容器里的裸文本一<p>容器里的段落</p>容器里的裸文本二</div>
——全书完——
</body></html>
"""
path = os.path.join(OUT, "bare.html")
open(path, "w", encoding="utf-8").write(html)

doc = parse_document(path)
print("解析块:")
for b in doc.blocks:
    print(f"   [{b.kind}] {b.text[:40]}")
texts = [b.text for b in doc.blocks]
assert any("文末游离文字" in t for t in texts), "body 裸文本丢失!"
assert any("容器里只有文本" in t for t in texts), "纯文本容器丢失!"
assert any("容器里的裸文本一" in t for t in texts), "混合容器前置裸文本丢失!"
assert any("容器里的裸文本二" in t for t in texts), "混合容器后置裸文本丢失!"
assert any("全书完" in t for t in texts), "文末全书完丢失!"
print("\n裸文本全部保留 ✓")

chs, notes = segment(doc, SegmentOptions(mode="auto", max_level=1))
build_epub(chs, BookMeta(title=doc.title), os.path.join(OUT, "bare.epub"), images=doc.images)
print("EPUB 生成 ✓ | 章节:", [c.title for c in chs])
print("警告:", doc.warnings)
