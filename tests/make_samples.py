# -*- coding: utf-8 -*-
"""生成测试样例：PNG 插图 / DOCX 报告 / PDF 手册。

用法: python tests/make_samples.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS = os.path.join(ROOT, ".deps")
if os.path.isdir(DEPS):
    sys.path.insert(0, DEPS)

SAMPLES = os.path.join(ROOT, "samples")
ASSETS = os.path.join(SAMPLES, "assets")


def make_png():
    """用 PIL 画一张简单的示意图。"""
    from PIL import Image, ImageDraw
    os.makedirs(ASSETS, exist_ok=True)
    img = Image.new("RGB", (480, 240), "#f0f4ff")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 460, 220], outline="#3366cc", width=4)
    d.ellipse([120, 60, 220, 160], fill="#ff9966", outline="#cc6633", width=3)
    d.rectangle([260, 90, 380, 150], fill="#66cc99", outline="#339966", width=3)
    for i, t in enumerate(["Epub", "Forge"]):
        d.text((170 + i * 60, 190), t, fill="#333366")
    out = os.path.join(ASSETS, "demo.png")
    img.save(out)
    print("生成:", out)


def make_docx():
    """用 python-docx 生成带标题样式与图片的报告。"""
    import docx
    from docx.shared import Inches

    os.makedirs(ASSETS, exist_ok=True)
    d = docx.Document()
    d.add_heading("季度研发报告", level=0)
    d.add_paragraph("本报告汇总本季度 Epub Forge 项目的研发进展。")

    d.add_heading("一、功能进展", level=1)
    d.add_paragraph("本季度完成了多格式解析与自动分章引擎，支持 TXT、Markdown、HTML、DOCX、PDF 五种输入格式。")
    d.add_paragraph("自动分章引擎可以识别文档自带的标题结构，并在结构缺失时通过正则探测纯文本标题。")

    d.add_heading("1.1 分章准确率", level=2)
    d.add_paragraph("在内部测试集上，结构类文档的分章准确率达到 100%，纯文本类文档达到 92%。")

    d.add_heading("1.2 界面改进", level=2)
    d.add_paragraph("桌面界面升级为 PySide6，支持拖拽导入、章节预览、重命名与合并。")

    d.add_heading("二、下一步计划", level=1)
    d.add_paragraph("下一季度将支持更多输出选项，包括字体嵌入与自定义样式模板。")

    # 插入示例图
    png = os.path.join(ASSETS, "demo.png")
    if os.path.exists(png):
        d.add_picture(png, width=Inches(3))

    out = os.path.join(SAMPLES, "report.docx")
    d.save(out)
    print("生成:", out)


def make_pdf():
    """用 PyMuPDF 生成带书签大纲与大字标题的手册。"""
    import pymupdf as fitz

    sections = [
        ("第一章 快速开始",
         "把源文档拖入窗口即可开始转换。程序会自动解析内容并分章。"),
        ("第二章 分章设置",
         "分章模式包括自动检测、按标题、自定义正则与按篇幅四种。"),
        ("2.1 自动检测",
         "自动检测优先使用文档结构标题，其次正则探测，最后按篇幅兜底。"),
        ("2.2 自定义正则",
         "例如 ^第[0-9]+章 可以匹配第一章、第二章等标题行。"),
        ("第三章 常见问题",
         "扫描版 PDF 需要先进行 OCR 才能转换。"),
    ]
    doc = fitz.open()
    toc = []
    for idx, (title, body) in enumerate(sections):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 140), title,
                            fontsize=22 if idx else 28, fontname="china-s")
        page.insert_textbox(fitz.Rect(72, 160, 540, 400), body,
                            fontsize=12, fontname="china-s")
        # 书签指向真实页码（level 1 章 / level 2 节）
        lvl = 2 if title.startswith("2.") else 1
        toc.append([lvl, title, idx + 1])
    doc.set_toc(toc)

    out = os.path.join(SAMPLES, "manual.pdf")
    doc.save(out)
    doc.close()
    print("生成:", out)


def make_plain_pdf():
    """无书签 PDF：标题由字号启发式识别（测试兜底路径）。"""
    import pymupdf as fitz

    doc = fitz.open()
    sections = [
        ("第一章 安装", "下载安装包后双击即可完成安装。"),
        ("第二章 配置", "打开设置面板，选择语言与输出目录。"),
        ("第三章 使用", "把文件拖入窗口，点击生成。"),
        ("第四章 卸载", "在系统设置中卸载即可。"),
    ]
    for title, body in sections:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 140), title, fontsize=24, fontname="china-s")
        for i, ln in enumerate(body.split("。")):
            if ln:
                page.insert_textbox(fitz.Rect(72, 180 + i * 40, 540, 240), ln + "。",
                                    fontsize=12, fontname="china-s")
    out = os.path.join(SAMPLES, "plain.pdf")
    doc.save(out)
    doc.close()
    print("生成:", out)


if __name__ == "__main__":
    make_png()
    make_docx()
    make_pdf()
    make_plain_pdf()
    print("样例生成完毕。")
