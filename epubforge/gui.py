# -*- coding: utf-8 -*-
"""Epub Forge 桌面 GUI（PySide6）。

布局:
  源文件选择 → 分章设置 + 章节预览(可重命名/合并) → 元数据 → 生成 EPUB
后台线程解析与构建，进度实时显示。
"""

from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QSpinBox, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from . import __version__, logutil
from .blocks import Chapter, ParsedDocument
from .builder import BookMeta, build_epub
from .chapter import SegmentOptions, segment
from .sources import SUPPORTED_EXT, detect_format, parse_document
from .utils import human_size

def _app_icon() -> QIcon | None:
    """窗口图标: 优先包内 assets/app.ico, 兼容 PyInstaller 解包目录。"""
    candidates = []
    base = getattr(sys, "_MEIPASS", None)  # onefile 解包临时目录
    if base:
        candidates.append(os.path.join(base, "assets", "app.ico"))
    candidates.append(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "assets", "app.ico"))
    for p in candidates:
        if os.path.exists(p):
            return QIcon(p)
    return None


LANG_CHOICES = [
    ("简体中文", "zh"), ("繁體中文", "zh-TW"), ("English", "en"),
    ("日本語", "ja"), ("한국어", "ko"), ("Deutsch", "de"), ("Français", "fr"),
]

MODE_HINTS = {
    "auto": "优先结构标题（MD/HTML/DOCX/PDF书签），不足则正则探测，再按篇幅兜底。",
    "heading": "只用文档自带结构标题（按级别上限），不足按篇幅兜底。",
    "regex": "用自定义正则匹配标题行，未命中按篇幅兜底。",
    "size": "忽略标题，纯按段落数切分。",
}

# 「生成 EPUB」就绪时的绿色样式；未就绪时使用默认主题配色（与其他按钮一致）
GEN_BTN_GREEN_QSS = (
    "QPushButton{background-color:#27ae60; color:white; border:none; border-radius:5px;"
    " font-size:14px; font-weight:bold; padding:4px 16px;}"
    "QPushButton:hover{background-color:#2ecc71;}"
    "QPushButton:pressed{background-color:#1e8449;}"
)


class Worker(QThread):
    """在后台线程执行任务，向 GUI 回传进度/结果。"""

    log = Signal(str)
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(self._emit_progress, *self._args, **self._kwargs)
            self.done.emit(result)
        except Exception as exc:
            self.failed.emit(f"{exc}\n{traceback.format_exc()}")

    def _emit_progress(self, pct: float, msg: str):
        self.progress.emit(float(pct), str(msg))


# --------------------------------------------------------------------------
# 后台任务
# --------------------------------------------------------------------------

def _analyze_task(path: str, opts: SegmentOptions, txt_mode: str, ocr_enabled: bool, cb):
    cb(5, "读取并解析源文档…")
    doc = parse_document(path, txt_para_mode=txt_mode, ocr=ocr_enabled, progress_cb=cb)
    cb(55, f"解析完成（{len(doc.blocks)} 个内容块），正在分章…")
    chapters, notes = segment(doc, opts)
    cb(100, "分章完成")
    return doc, chapters, notes


def _build_task(doc: ParsedDocument, chapters: list[Chapter], meta: BookMeta,
                out_path: str, cover_bytes, cover_name, cb):
    return build_epub(chapters, meta, out_path, images=doc.images,
                      cover_bytes=cover_bytes, cover_name=cover_name, progress_cb=cb)


# --------------------------------------------------------------------------
# 主窗口
# --------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Epub Forge v{__version__} — 多格式文档转 EPUB")
        _icon = _app_icon()
        if _icon is not None:
            self.setWindowIcon(_icon)
        self.resize(1080, 760)
        self.setAcceptDrops(True)

        self.doc: ParsedDocument | None = None
        self.chapters: list[Chapter] | None = None
        self.worker: Worker | None = None
        self.source_path: str = ""

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)

        root.addLayout(self._build_source_row())
        root.addWidget(self._build_splitter(), stretch=1)
        root.addWidget(self._build_meta_group())
        root.addLayout(self._build_action_row())

        # 输出文件预览联动（书名/输出目录变化时刷新）
        self.title_edit.textChanged.connect(self._update_out_preview)
        self.out_edit.textChanged.connect(self._update_out_preview)

        self._apply_mode_ui()
        self._log(f"Epub Forge v{__version__} 就绪。支持格式: {', '.join(sorted(SUPPORTED_EXT))}")
        self._log("拖拽文件到窗口，或点击「浏览…」选择源文档。")
        self._log("运行日志写入程序目录 logs/ 文件夹（按天分文件）。")
        self.statusBar().showMessage(f"日志目录: {logutil.log_dir()}", 8000)

    # ---------------- UI 构建 ----------------

    def _build_source_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("源文件:"))
        self.src_edit = QLineEdit()
        self.src_edit.setPlaceholderText("选择或拖入 .txt / .md / .html / .docx / .pdf 文件…")
        self.src_edit.setReadOnly(True)
        row.addWidget(self.src_edit, stretch=1)
        self.fmt_label = QLabel("—")
        self.fmt_label.setStyleSheet("color:#888;")
        row.addWidget(self.fmt_label)
        btn = QPushButton("浏览…")
        btn.clicked.connect(self._pick_source)
        row.addWidget(btn)
        return row

    def _build_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Horizontal)

        # ---- 左：分章设置 + 章节预览 ----
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 8, 0)

        g = QGroupBox("分章设置")
        form = QFormLayout(g)
        self.mode_combo = QComboBox()
        for key, label in [("auto", "自动检测（推荐）"), ("heading", "按文档标题"),
                           ("regex", "自定义正则"), ("size", "按篇幅")]:
            self.mode_combo.addItem(label, key)
        self.mode_combo.currentIndexChanged.connect(self._apply_mode_ui)
        form.addRow("检测模式:", self.mode_combo)

        self.max_level_spin = QSpinBox()
        self.max_level_spin.setRange(0, 6)
        self.max_level_spin.setValue(1)
        self.max_level_spin.setSpecialValueText("不限")
        form.addRow("标题级别上限:", self.max_level_spin)

        self.regex_edit = QLineEdit()
        self.regex_edit.setPlaceholderText(r"如: ^第[0-9一二三四五六七八九十]+[章节]")
        form.addRow("章节正则:", self.regex_edit)

        self.paras_spin = QSpinBox()
        self.paras_spin.setRange(2, 200)
        self.paras_spin.setValue(8)
        form.addRow("每章段落数:", self.paras_spin)

        self.minchars_spin = QSpinBox()
        self.minchars_spin.setRange(0, 100000)
        self.minchars_spin.setValue(500)
        self.minchars_spin.setSingleStep(100)
        form.addRow("少于多少字不分章:", self.minchars_spin)

        self.no_split_radio = QRadioButton("不分章（整本作为一章）")
        self.no_split_radio.toggled.connect(self._apply_no_split_ui)
        form.addRow("分章控制:", self.no_split_radio)

        self.txt_mode_combo = QComboBox()
        for label, key in [("自动（推荐）", "auto"), ("空行分段", "blank"), ("每行一段", "line")]:
            self.txt_mode_combo.addItem(label, key)
        form.addRow("TXT 分段:", self.txt_mode_combo)

        self.ocr_check = QCheckBox("扫描版 PDF 自动 OCR（无文字层时，速度较慢）")
        self.ocr_check.setChecked(True)
        form.addRow("OCR:", self.ocr_check)
        lv.addWidget(g)

        self.mode_hint = QLabel("")
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setStyleSheet("color:#777; font-size:11px;")
        lv.addWidget(self.mode_hint)

        lv.addWidget(QLabel("章节预览:"))
        self.chapter_list = QListWidget()
        self.chapter_list.itemDoubleClicked.connect(self._rename_chapter)
        self.chapter_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chapter_list.customContextMenuRequested.connect(self._chapter_menu)
        lv.addWidget(self.chapter_list, stretch=1)

        # ---- 右：输出 + 章节工具 + 生成 ----
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 0, 0, 0)

        g2 = QGroupBox("输出")
        f2 = QFormLayout(g2)
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setMinimumHeight(28)
        out_row.addWidget(self.out_edit, stretch=1)
        out_btn = QPushButton("浏览…")
        out_btn.clicked.connect(self._pick_outdir)
        out_row.addWidget(out_btn)
        f2.addRow("输出目录:", out_row)

        cover_row = QHBoxLayout()
        self.cover_edit = QLineEdit()
        self.cover_edit.setMinimumHeight(28)
        self.cover_edit.setPlaceholderText("可选：封面图片 (jpg/png)")
        cover_row.addWidget(self.cover_edit, stretch=1)
        cover_btn = QPushButton("选择…")
        cover_btn.clicked.connect(self._pick_cover)
        cover_row.addWidget(cover_btn)
        f2.addRow("封面:", cover_row)

        self.out_preview = QLabel("输出文件：—")
        self.out_preview.setWordWrap(True)
        self.out_preview.setStyleSheet("color:#556; font-size:11px;")
        f2.addRow("", self.out_preview)
        rv.addWidget(g2)

        self.chapter_stats = QLabel("尚未分析")
        self.chapter_stats.setStyleSheet("color:#555;")
        rv.addWidget(self.chapter_stats)

        # 操作按钮组：分析章节 → 重命名/合并 → 生成（绿色）
        analyze_btn = QPushButton("分析章节")
        analyze_btn.setMinimumHeight(34)
        analyze_btn.clicked.connect(self._analyze)
        rv.addWidget(analyze_btn)

        btn_row = QHBoxLayout()
        rename_btn = QPushButton("重命名")
        rename_btn.clicked.connect(lambda: self._rename_chapter())
        merge_btn = QPushButton("与上一章合并")
        merge_btn.clicked.connect(self._merge_prev)
        btn_row.addWidget(rename_btn)
        btn_row.addWidget(merge_btn)
        rv.addLayout(btn_row)

        self.gen_btn = QPushButton("生成 EPUB")
        self.gen_btn.setEnabled(False)  # 未就绪：默认配色（与其他按钮一致）
        self.gen_btn.setMinimumHeight(40)
        self.gen_btn.clicked.connect(self._build)
        rv.addWidget(self.gen_btn)
        rv.addStretch(1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([540, 430])
        return splitter

    def _build_meta_group(self) -> QGroupBox:
        g = QGroupBox("元数据")
        form = QFormLayout(g)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.title_edit = QLineEdit()
        self.author_edit = QLineEdit()
        self.publisher_edit = QLineEdit()
        self.lang_combo = QComboBox()
        for label, code in LANG_CHOICES:
            self.lang_combo.addItem(label, code)
        self.lang_combo.setCurrentIndex(0)
        self.desc_edit = QTextEdit()
        self.desc_edit.setFixedHeight(64)
        self.desc_edit.setPlaceholderText("可选：书籍简介")
        form.addRow("书名:", self.title_edit)
        form.addRow("作者:", self.author_edit)
        form.addRow("出版社:", self.publisher_edit)
        form.addRow("语言:", self.lang_combo)
        form.addRow("简介:", self.desc_edit)
        return g

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p% — %v")
        row.addWidget(self.progress, stretch=1)
        return row

    # ---------------- 交互 ----------------

    def _log(self, msg: str):
        """写入文件日志（程序目录 logs/ 文件夹）。"""
        logutil.log(msg)

    def _apply_mode_ui(self):
        mode = self.mode_combo.currentData()
        self.mode_hint.setText(MODE_HINTS.get(mode, ""))
        self._apply_no_split_ui()

    def _apply_no_split_ui(self):
        """「不分章」选中时，禁用全部分章相关控件。"""
        off = self.no_split_radio.isChecked()
        mode = self.mode_combo.currentData()
        self.mode_combo.setEnabled(not off)
        self.max_level_spin.setEnabled(not off and mode in ("auto", "heading"))
        self.regex_edit.setEnabled(not off and mode == "regex")
        self.paras_spin.setEnabled(not off and mode == "size")
        self.minchars_spin.setEnabled(not off)

    def _opts(self) -> SegmentOptions:
        return SegmentOptions(
            mode=self.mode_combo.currentData(),
            max_level=self.max_level_spin.value(),
            custom_regex=self.regex_edit.text().strip(),
            paras_per_chunk=self.paras_spin.value(),
            min_chars=self.minchars_spin.value(),
            no_split=self.no_split_radio.isChecked(),
        )

    def _update_out_preview(self):
        """根据输出目录与书名刷新「输出文件」预览。"""
        outdir = self.out_edit.text().strip()
        if not outdir or not self.source_path:
            self.out_preview.setText("输出文件：—")
            return
        title = self.title_edit.text().strip() or (self.doc.title if self.doc else "") or "未命名"
        safe = "".join(c if c not in r'\/:*?"<>|' else "_" for c in title)
        self.out_preview.setText(f"输出文件：{os.path.join(outdir, safe + '.epub')}")

    def _pick_source(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择源文档", "",
            "支持格式 (*.txt *.md *.markdown *.html *.htm *.xhtml *.docx *.pdf);;所有文件 (*)")
        if path:
            self._set_source(path)

    def _set_gen_enabled(self, enabled: bool):
        """「生成 EPUB」按钮：就绪时绿色，未就绪时默认主题配色（与其他按钮一致）。"""
        self.gen_btn.setEnabled(enabled)
        if enabled:
            self.gen_btn.setStyleSheet(GEN_BTN_GREEN_QSS)
        else:
            self.gen_btn.setStyleSheet("")

    def _clear_form(self, clear_source: bool):
        """清除上一次填写/选择的内容（元数据、封面、章节、源文件）。"""
        self.doc = None
        self.chapters = None
        self.title_edit.clear()
        self.author_edit.clear()
        self.publisher_edit.clear()
        self.desc_edit.clear()
        self.cover_edit.clear()
        self.chapter_list.clear()
        self.chapter_stats.setText("尚未分析")
        self.out_preview.setText("输出文件：—")
        self.progress.setValue(0)
        self._set_gen_enabled(False)
        if clear_source:
            self.source_path = ""
            self.src_edit.clear()
            self.fmt_label.setText("—")

    def _set_source(self, path: str):
        # 选择了新文件：先清掉上一次填写的元数据/封面/章节，避免串数据
        if path != self.source_path:
            self._clear_form(clear_source=False)
        self.source_path = path
        self.src_edit.setText(path)
        fmt = detect_format(path)
        self.fmt_label.setText(f"格式: {fmt.upper() if fmt else '不支持'}")
        if not fmt:
            self._set_gen_enabled(False)
            self._log(f"不支持的文件格式: {path}")
            return
        if not self.out_edit.text():
            self.out_edit.setText(os.path.dirname(os.path.abspath(path)))
        self._update_out_preview()
        self._log(f"已选择: {path}")
        self._analyze()

    def _pick_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.out_edit.text() or os.getcwd())
        if d:
            self.out_edit.setText(d)

    def _pick_cover(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择封面图片", "",
                                              "图片 (*.jpg *.jpeg *.png *.webp *.bmp)")
        if path:
            self.cover_edit.setText(path)
            self._log(f"封面: {path}")

    # ---------------- 分析 ----------------

    def _analyze(self):
        if not self.source_path or not detect_format(self.source_path):
            QMessageBox.warning(self, "提示", "请先选择支持的源文档。")
            return
        self._set_busy(True, "分析中…")
        self._log(f"开始分析: {os.path.basename(self.source_path)}")

        def task(cb):
            return _analyze_task(self.source_path, self._opts(),
                                 self.txt_mode_combo.currentData(),
                                 self.ocr_check.isChecked(), cb)

        self._start_worker(task, self._on_analyzed)

    def _on_analyzed(self, result):
        doc, chapters, notes = result
        self.doc = doc
        self.chapters = chapters
        self._set_busy(False, "")
        for w in doc.warnings:
            self._log(f"警告: {w}")
        for n in notes:
            self._log(f"分章: {n}")
        self._refresh_chapter_list()
        if not self.title_edit.text().strip():
            self.title_edit.setText(doc.title)
        self._update_out_preview()
        self._set_gen_enabled(bool(chapters))
        total = sum(c.text_len for c in chapters)
        src_size = human_size(os.path.getsize(self.source_path)) if os.path.isfile(self.source_path) else "?"
        self.chapter_stats.setText(f"{len(chapters)} 章 · 约 {total:,} 字 · 源文件 {src_size}")
        self._log(f"分析完成: {len(chapters)} 章")
        if doc.warnings:
            self.statusBar().showMessage(f"⚠ 分析产生 {len(doc.warnings)} 条提示/警告（详见程序目录 logs/ 日志）", 12000)

    # ---------------- 章节编辑 ----------------

    def _refresh_chapter_list(self):
        self.chapter_list.clear()
        bold = QFont()
        bold.setBold(True)
        prev_vol = None
        for i, ch in enumerate(self.chapters or [], 1):
            # 卷/部标题行：分组显示，不可选中（无 UserRole，编辑操作自动跳过）
            if ch.volume and ch.volume != prev_vol:
                sep = QListWidgetItem(f"▍{ch.volume}")
                sep.setFlags(Qt.NoItemFlags)
                sep.setForeground(QColor("#3a7ca5"))
                sep.setFont(bold)
                self.chapter_list.addItem(sep)
                prev_vol = ch.volume
            prefix = "    " if ch.volume else ""
            item = QListWidgetItem(
                f"{prefix}{i:>3}. {ch.title or '(无标题)'}    ——  {ch.block_count} 块 · {ch.text_len:,} 字")
            item.setData(Qt.UserRole, i - 1)
            self.chapter_list.addItem(item)

    def _selected_index(self) -> int | None:
        item = self.chapter_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _rename_chapter(self, item=None):
        idx = self._selected_index()
        if idx is None or self.chapters is None:
            return
        ch = self.chapters[idx]
        text, ok = QInputDialog.getText(self, "重命名章节", "新标题:", text=ch.title)
        if ok and text.strip():
            ch.title = text.strip()
            self._refresh_chapter_list()
            self._log(f"章节 {idx + 1} 重命名为: {ch.title}")

    def _merge_prev(self):
        idx = self._selected_index()
        if idx is None or idx == 0 or self.chapters is None:
            QMessageBox.information(self, "提示", "请选择第 2 章及之后的章节（第 1 章没有上一章）。")
            return
        prev, cur = self.chapters[idx - 1], self.chapters[idx]
        prev.merge(cur)
        del self.chapters[idx]
        self._refresh_chapter_list()
        self._log(f"已将「{cur.title}」并入「{prev.title}」")

    def _chapter_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("重命名", lambda: self._rename_chapter())
        menu.addAction("与上一章合并", self._merge_prev)
        menu.exec(self.chapter_list.mapToGlobal(pos))

    # ---------------- 生成 ----------------

    def _build(self):
        if self.doc is None or not self.chapters:
            QMessageBox.warning(self, "提示", "请先分析章节。")
            return
        title = self.title_edit.text().strip() or self.doc.title or "未命名"
        outdir = self.out_edit.text().strip() or os.path.dirname(os.path.abspath(self.source_path))
        os.makedirs(outdir, exist_ok=True)
        safe_title = "".join(c if c not in r'\/:*?"<>|' else "_" for c in title)
        out_path = os.path.join(outdir, f"{safe_title}.epub")

        meta = BookMeta(
            title=title,
            author=self.author_edit.text().strip(),
            lang=self.lang_combo.currentData(),
            publisher=self.publisher_edit.text().strip(),
            description=self.desc_edit.toPlainText().strip(),
        )

        cover_bytes, cover_name = None, "cover.jpg"
        if self.cover_edit.text().strip():
            cover_path = self.cover_edit.text().strip()
            if os.path.isfile(cover_path):
                with open(cover_path, "rb") as f:
                    cover_bytes = f.read()
                ext = os.path.splitext(cover_path)[1].lstrip(".").lower() or "jpg"
                cover_name = f"cover.{ext}"
            else:
                QMessageBox.warning(self, "提示", "封面文件不存在，已忽略。")

        self._set_busy(True, "生成中…")
        self._log(f"开始生成: {out_path}")
        # 复制章节时必须保留 volume 字段：丢失会导致生成的 EPUB 目录
        # 丢掉卷/部分组（预览正常但阅读器里平铺）
        chapters_copy = [Chapter(ch.title, list(ch.blocks), ch.volume)
                         for ch in self.chapters]
        meta_copy = meta

        def task(cb):
            return _build_task(self.doc, chapters_copy, meta_copy, out_path,
                               cover_bytes, cover_name, cb)

        self._start_worker(task, self._on_built, extra={"out": out_path})

    def _on_built(self, result):
        self._set_busy(False, "")
        out_path = result
        size = human_size(os.path.getsize(out_path))
        self.progress.setValue(100)
        self._log(f"生成成功: {out_path}（{size}）")
        box = QMessageBox(self)
        box.setWindowTitle("完成")
        box.setText(f"EPUB 生成成功！\n{out_path}\n（{size}）")
        open_btn = box.addButton("打开所在文件夹", QMessageBox.ActionRole)
        box.addButton("关闭", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(out_path)))
        # 生成完成：清除上一次填写的内容，方便开始下一次转换
        self._clear_form(clear_source=True)
        self._log("已清除表单内容，可以开始下一次转换。")

    # ---------------- 通用 ----------------

    def _set_busy(self, busy: bool, text: str):
        self._set_gen_enabled(not busy and bool(self.chapters))
        if busy:
            self.progress.setValue(0)
        self.statusBar().showMessage(text)

    def _start_worker(self, task, on_done, extra=None):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "提示", "已有任务在运行，请稍候。")
            return
        self.worker = Worker(task)
        self.worker.log.connect(self._log)
        self.worker.progress.connect(lambda p, m: (self.progress.setValue(int(p)), self.statusBar().showMessage(m)))
        self.worker.done.connect(on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_failed(self, err: str):
        self._set_busy(False, "")
        self._log(f"错误: {err.splitlines()[0] if err else '未知错误'}")
        QMessageBox.critical(self, "转换失败", err)

    # ---------------- 拖拽 ----------------

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            # 后台线程仍在跑（OCR 大 PDF 可能耗时数分钟）：直接销毁运行中的
            # QThread 会导致崩溃（"QThread: Destroyed while thread is still
            # running"），必须先让用户确认，而不是默默 wait 超时后强关。
            ret = QMessageBox.question(
                self, "任务进行中",
                "后台转换任务仍在运行，现在退出可能导致程序异常。\n确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.wait(3000)
        event.accept()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.isfile(path):
                self._set_source(path)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Epub Forge")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
