# -*- coding: utf-8 -*-
"""模拟用户反馈的轻小说 TXT 结构（行首全角空格、对话、章节标题、文末（全书完）），
验证转换后文末内容是否完整保留。"""
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS = os.path.join(ROOT, ".deps")
if os.path.isdir(DEPS):
    sys.path.insert(0, DEPS)

from epubforge.builder import BookMeta, build_epub  # noqa: E402
from epubforge.chapter import SegmentOptions, segment  # noqa: E402
from epubforge.sources import parse_document  # noqa: E402

OUT = os.path.join(ROOT, "test_out")
os.makedirs(OUT, exist_ok=True)

TAIL = [
    "总之，希望这傢伙能跟我一样获得自己的「幸福」",
    "　　我跟身边的三位女性就这么踏上了回家的归途，结束了难得一次的温泉旅行。（全书完）",
]


def build_light_novel(path: str, use_blank_lines: bool = True):
    """生成轻小说风格文档：章节标题 + 带全角空格缩进的段落。"""
    lines = ["温泉旅行"]
    for ch in range(1, 21):
        lines.append(f"第{ch}章")
        lines.append(f"　　「明天去泡温泉吧。」{ch}号的她笑着说。")
        lines.append(f"　　「好啊，好久没去了。」我答道。")
        lines.append(f"　　{ch}号心里想着些什么，脸上却挂着淡淡的微笑。")
        if ch % 4 == 0:
            lines.append("间章")
            lines.append(f"　　「{ch}号，你有心事吗？」")
            lines.append(f"　　「没有哦。」她摇了摇头，目光却飘向了远方。")
    lines.extend(TAIL)
    if use_blank_lines:
        content = "\n\n".join(lines) + "\n"
    else:
        content = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def extract_epub_text(path: str) -> str:
    chunks = []
    with zipfile.ZipFile(path) as z:
        for n in sorted(z.namelist()):
            if re.search(r"text/chap\d+\.xhtml$", n):
                html = z.read(n).decode("utf-8")
                body = re.search(r"<body>(.*)</body>", html, re.S)
                if body:
                    chunks.append(re.sub(r"<[^>]+>", "", body.group(1)))
    return "".join(chunks)


def test(label, path):
    doc = parse_document(path)
    chs, notes = segment(doc, SegmentOptions(mode="auto", max_level=1))
    epub_path = os.path.join(OUT, f"ln_{label}.epub")
    build_epub(chs, BookMeta(title=doc.title), epub_path, images=doc.images)
    text = extract_epub_text(epub_path)

    print(f"\n===== {label} =====")
    print(f"  警告: {doc.warnings}")
    print(f"  章节数: {len(chs)}, 总块数: {len(doc.blocks)}")
    ok = True
    for tail_line in TAIL:
        # 逐字核对其中的特征片段（全书完、幸福、归途）
        frag = tail_line[-12:]  # 取末尾 12 字（含（全书完）片段）
        present = frag in text
        print(f"  尾行片段 {frag!r}: {'存在' if present else '丢失!!'}")
        ok = ok and present
    # 末章内容
    last = chs[-1] if chs else None
    print(f"  末章标题: {last.title if last else '无'}, 末章块数: {last.block_count if last else 0}")
    print(f"  末章末块: {last.blocks[-1].text[:50] if last and last.blocks else '空'}")
    return 0 if ok else 1


def main():
    for blank in (True, False):
        label = "blank" if blank else "line"
        path = os.path.join(OUT, f"light_novel_{label}.txt")
        build_light_novel(path, blank)
        test(label, path)
    print("\n完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
