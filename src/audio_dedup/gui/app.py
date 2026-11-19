"""音频重复识别工具 · PySide6 主窗口。

页面：顶栏（工作目录）→ 统计卡片 → 筛选与操作条 → 左分组列表＋目录树 / 右文件表＋波形＋播放＋日志。
所有处置动作都要求人类逐次确认；源库全程只读，唯一写动作是「移入隔离文件夹」（可恢复）。
"""
import argparse
import os
import sys

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import quarantine
from . import data, theme
from .widgets import PAD_TOP, TRACK_H, StatCard, WaveformWidget

DEFAULT_WORKDIR = "D:/Ai-Files/Repos/audio-dedup/build/scan-20261109"

# 列序常量：改造列结构时只改这里，避免魔法数字散落各处
F_PLAY, F_CHECK, F_NAME, F_SIZE, F_DUR, F_BER, F_HINT, F_PATH = range(8)
G_ID, G_LAYER, G_COUNT, G_GRADE, G_RECLAIM = range(5)

# 超过这个数量的批量隔离，确认框强制勾选「已核对清单」
BULK_CONFIRM_THRESHOLD = 50

# 波形轨道上限：组内文件多于此时只显示前 N 条（避免极端组拖垮解码队列）
WAVE_TRACK_LIMIT = 60


def _icon_path():
    """图标真源：源码运行取包内 assets，打包运行取 PyInstaller 解包目录。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.join(getattr(sys, "_MEIPASS", "") or "", "audio_dedup", "gui")):
        for name in ("app.ico", "app.png"):
            candidate = os.path.join(base, "assets", name)
            if os.path.isfile(candidate):
                return candidate
    return ""


def _brand_path():
    """顶栏两行字标：源码运行取包内 assets，打包运行取解包目录。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.join(getattr(sys, "_MEIPASS", "") or "", "audio_dedup", "gui")):
        candidate = os.path.join(base, "assets", "brand.png")
        if os.path.isfile(candidate):
            return candidate
    return ""


def _mmss(sec: float) -> str:
    sec = max(0, int(sec or 0))
    return f"{sec // 60:02d}:{sec % 60:02d}"


class _PeaksSignals(QObject):
    done = Signal(str, int, object)


class _PeaksTask(QRunnable):
    def __init__(self, path, ffmpeg, token, signals):
        super().__init__()
        self.path, self.ffmpeg, self.token, self.signals = path, ffmpeg, token, signals

    def run(self):
        try:
            from ..core import peaks
            result = peaks.peaks(self.path, self.ffmpeg)
        except Exception:  # noqa: BLE001 - 单个坏文件不得打断线程池
            result = None
        self.signals.done.emit(self.path, self.token, result)


class Player(QObject):
    """试听：Qt 多媒体后端；不可用时由界面回退到系统默认播放器。"""

    position = Signal(float)
    duration = Signal(float)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.available = True
        try:
            self._player = QMediaPlayer()
            self._audio = QAudioOutput()
            self._player.setAudioOutput(self._audio)
            self._audio.setVolume(0.8)
            self._player.positionChanged.connect(lambda ms: self.position.emit(ms / 1000.0))
            self._player.durationChanged.connect(lambda ms: self.duration.emit(ms / 1000.0))
            self._player.errorOccurred.connect(lambda _e, msg: self.failed.emit(msg))
        except Exception as exc:  # noqa: BLE001 - 外部数据与 Qt 后端异常统一兜底并提示用户
            self.available = False
            self.failed.emit(str(exc))

    def play(self, path):
        if not self.available:
            return False
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()
        return True

    def pause(self):
        if self.available:
            self._player.pause()

    def stop(self):
        if self.available:
            self._player.stop()

    def seek(self, sec):
        if self.available:
            self._player.setPosition(int(sec * 1000))

    def set_volume(self, value):
        if self.available:
            self._audio.setVolume(value / 100.0)


class TaskRunner(QObject):
    """后台跑 CLI，stdout 实时进日志面板；同一时刻只允许一个任务。"""

    output = Signal(str)
    finished = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.proc = None

    def running(self):
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def start(self, label, args):
        if self.running():
            return False
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        if getattr(sys, "frozen", False):
            args = ["--cli"] + args[2:]  # 打包版由同一 exe 分发 CLI 子命令
        self.proc = QProcess(self)
        self.proc.setProcessEnvironment(env)
        self.proc.setProgram(sys.executable)
        self.proc.setArguments(args)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(lambda code, _status: self._done(label, code))
        self.output.emit(f"$ {' '.join(args)}")
        self.proc.start()
        return True

    def _read(self):
        while self.proc.canReadLine():
            text = bytes(self.proc.readLine()).decode("utf-8", errors="replace").rstrip()
            if text:
                self.output.emit(text)

    def _done(self, label, code):
        self.output.emit(f"[{label}] 结束，退出码 {code}")
        self.finished.emit(code, label)


APP_VERSION = "0.1.1"


class MainWindow(QMainWindow):
    def __init__(self, workdir=None, ffmpeg="ffmpeg"):
        super().__init__()
        self.setWindowTitle("音频重复识别工具")
        self.resize(1560, 980)
        self.setStyleSheet(theme.QSS)
        icon = _icon_path()
        if icon:
            self.setWindowIcon(QIcon(icon))
        self.ffmpeg = ffmpeg
        self.workdir = workdir or ""
        self.root = ""
        self.qdir = ""
        self.payload = None
        self.groups_all = []
        self.groups_view = []
        self.current_group = None
        self.checked = set()
        self.dir_filter = ""
        self._loading = False
        self._duration = 0.0
        self._peaks_token = 0
        self._wave_paths = []
        self._track_results = []
        self._current_audio = ""

        # 数值列用等宽字体（对齐 SFX Tools 的数据口径），中文列保持雅黑
        self._mono_font = QFont("Consolas", 9)

        # 搜索防抖：避免每敲一个字就重建分组表并触发全组波形解码
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(lambda: self._apply_filters())

        self._build_ui()
        self._init_async()
        if self.workdir:
            QTimer.singleShot(60, lambda: self.open_workdir(self.workdir))
        else:
            self._log("请选择包含 groups.json 或 index.sqlite3 的索引工作目录。")

    # ---------------------------------------------------------------- 界面

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._make_topbar())
        lay.addWidget(self._make_stats())
        lay.addWidget(self._make_toolbar())
        lay.addLayout(self._make_body(), 1)
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.addPermanentWidget(QLabel(f"音频重复识别工具 | v{APP_VERSION}"))
        self.status.showMessage("就绪  ·  源库只读，任何处置都需逐次确认")

    def _make_topbar(self):
        bar = QFrame()
        bar.setObjectName("Topbar")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 6, 18, 6)
        lay.setSpacing(10)
        brand = QLabel()
        bp = _brand_path()
        if bp:
            pm = QPixmap(bp)
            if not pm.isNull():
                brand.setPixmap(pm.scaledToHeight(34, Qt.SmoothTransformation))
        brand.setObjectName("Brand")
        title = QLabel("音频重复识别工具")
        title.setObjectName("Title")
        tv = QVBoxLayout()
        tv.setSpacing(0)
        tv.addWidget(title)
        lay.addWidget(brand)
        lay.addLayout(tv)
        lay.addSpacing(14)
        lay.addWidget(QLabel("工作目录"))
        self.workdir_edit = QLineEdit(self.workdir)
        self.workdir_edit.setPlaceholderText("索引与报告所在目录（groups.json / index.sqlite3）")
        self.workdir_edit.returnPressed.connect(
            lambda: self.open_workdir(self.workdir_edit.text()))
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._pick_workdir)
        open_btn = QPushButton("打开索引")
        open_btn.setObjectName("Primary")
        open_btn.clicked.connect(lambda: self.open_workdir(self.workdir_edit.text()))
        badge = QLabel("源库只读 · 无永久删除")
        badge.setObjectName("Badge")
        lay.addWidget(self.workdir_edit, 1)
        lay.addWidget(browse)
        lay.addWidget(open_btn)
        lay.addWidget(badge)
        return bar

    def _make_stats(self):
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(16, 8, 16, 6)
        lay.setSpacing(10)
        # 只有「预计可释放」上金色：它是唯一的收益指标，其余保持中性
        self.card_files = StatCard("已索引文件")
        self.card_groups = StatCard("重复 / 疑似组")
        self.card_reclaim = StatCard("预计可释放", theme.ACCENT)
        self.card_edges = StatCard("L3 相似边", theme.MUTED)
        for card in (self.card_files, self.card_groups, self.card_reclaim, self.card_edges):
            lay.addWidget(card)
        lay.addStretch(1)
        note = QLabel("保留建议：无损优先 → 码率优先 → 路径短优先")
        note.setObjectName("Subtitle")
        lay.addWidget(note)
        return box

    def _make_toolbar(self):
        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(16, 2, 16, 8)
        outer.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel("判定层"))
        self.layer_combo = QComboBox()
        self.layer_combo.addItems(["全部", "L1 字节级", "L2 音频级", "L3 感知疑似"])
        self.layer_combo.setFixedWidth(130)
        self.layer_combo.currentIndexChanged.connect(lambda _i: self._apply_filters())
        row1.addWidget(self.layer_combo)
        row1.addWidget(QLabel("等级"))
        self.grade_combo = QComboBox()
        self.grade_combo.addItems(["全部等级", "确定", "高疑似", "中疑似", "低疑似"])
        self.grade_combo.setFixedWidth(110)
        self.grade_combo.currentIndexChanged.connect(lambda _i: self._apply_filters())
        row1.addWidget(self.grade_combo)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索文件名 / 路径 / 组号…")
        self.search_edit.textChanged.connect(lambda _t: self._search_timer.start())
        row1.addWidget(self.search_edit, 1)
        self.filter_label = QLabel("—")
        self.filter_label.setObjectName("Subtitle")
        row1.addWidget(self.filter_label)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.btn_scan = QPushButton("重新扫描 L1/L2")
        self.btn_scan.clicked.connect(self._run_scan)
        self.btn_l3 = QPushButton("跑 L3 感知匹配")
        self.btn_l3.clicked.connect(self._run_l3)
        self.btn_report = QPushButton("导出报告")
        self.btn_report.clicked.connect(self._export_report)
        self.btn_refresh = QPushButton("刷新数据")
        self.btn_refresh.clicked.connect(self._reload)
        self.btn_select = QPushButton("勾选重复项")
        self.btn_select.clicked.connect(self._select_duplicates)
        self.btn_quarantine = QPushButton("移入隔离区")
        self.btn_quarantine.setObjectName("Danger")
        self.btn_quarantine.clicked.connect(self._quarantine_selected)
        self.btn_restore = QPushButton("恢复批次")
        self.btn_restore.clicked.connect(self._restore_batch)
        for btn in (self.btn_scan, self.btn_l3, self.btn_report, self.btn_refresh,
                    self.btn_select, self.btn_quarantine, self.btn_restore):
            row2.addWidget(btn)
        row2.addStretch(1)
        self.qdir_label = QLabel("隔离区：未设置")
        self.qdir_label.setObjectName("Subtitle")
        row2.addWidget(self.qdir_label)
        outer.addLayout(row2)
        return box

    def _make_body(self):
        outer = QHBoxLayout()
        outer.setContentsMargins(16, 0, 16, 12)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        left_split = QSplitter(Qt.Vertical)
        left_split.setChildrenCollapsible(False)
        left_split.addWidget(self._make_group_panel())
        left_split.addWidget(self._make_dir_panel())
        left_split.setStretchFactor(0, 3)
        left_split.setStretchFactor(1, 2)
        left_split.setSizes([520, 380])
        lv.addWidget(left_split)
        splitter.addWidget(left)

        right = QSplitter(Qt.Vertical)
        right.setChildrenCollapsible(False)

        files_panel = QWidget()
        fv = QVBoxLayout(files_panel)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(6)
        frow = QHBoxLayout()
        frow.setSpacing(8)
        fsec = QLabel("组内文件  ·  FILES（勾选要移入隔离区的非保留项）")
        fsec.setObjectName("SectionTitle")
        frow.addWidget(fsec)
        frow.addStretch(1)
        self.file_scope_label = QLabel("—")
        self.file_scope_label.setObjectName("Subtitle")
        frow.addWidget(self.file_scope_label)
        fv.addLayout(frow)
        self.file_table = QTableWidget(0, 8)
        self.file_table.setHorizontalHeaderLabels(
            ["▶", "隔离", "文件", "大小", "时长", "BER", "建议", "完整路径"])
        self._setup_table(self.file_table, [40, 54, 170, 78, 68, 58, 72, 460])
        self.file_table.setTextElideMode(Qt.ElideMiddle)
        self.file_table.itemChanged.connect(self._on_check_changed)
        self.file_table.itemSelectionChanged.connect(self._on_file_selected)
        self.file_table.doubleClicked.connect(lambda _idx: self._play_selected())
        fv.addWidget(self.file_table)
        right.addWidget(files_panel)

        wave_panel = QWidget()
        wv = QVBoxLayout(wave_panel)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(6)
        wsec = QLabel("波形对比 / 试听  ·  WAVEFORM & PREVIEW")
        wsec.setObjectName("SectionTitle")
        whead = QHBoxLayout()
        whead.setSpacing(8)
        whead.addWidget(wsec)
        whead.addStretch(1)
        self.wave_pos_label = QLabel("—")
        self.wave_pos_label.setObjectName("Subtitle")
        whead.addWidget(self.wave_pos_label)
        wv.addLayout(whead)
        self.waveform = WaveformWidget()
        self.waveform.seekRequested.connect(self._on_wave_seek)
        self.waveform.trackSelected.connect(self._on_wave_track_selected)
        self.waveform.trackActivated.connect(self._on_wave_track_activated)
        self.wave_scroll = QScrollArea()
        self.wave_scroll.setWidget(self.waveform)
        self.wave_scroll.setWidgetResizable(True)
        self.wave_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.wave_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        wv.addWidget(self.wave_scroll, 1)
        wv.addLayout(self._make_player_bar())
        right.addWidget(wave_panel)

        self.tabs = QTabWidget()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.detail_view = QPlainTextEdit()
        self.detail_view.setReadOnly(True)
        self.tabs.addTab(self.log_view, "任务日志")
        self.tabs.addTab(self.detail_view, "组详情 / 相似边")
        right.addWidget(self.tabs)
        right.setStretchFactor(0, 4)
        right.setStretchFactor(1, 5)
        right.setStretchFactor(2, 2)
        right.setSizes([360, 420, 120])

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([440, 1080])
        outer.addWidget(splitter)
        return outer

    def _make_group_panel(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        sec = QLabel("分组列表  ·  GROUPS")
        sec.setObjectName("SectionTitle")
        head.addWidget(sec)
        head.addStretch(1)
        self.group_scope_label = QLabel("—")
        self.group_scope_label.setObjectName("Subtitle")
        head.addWidget(self.group_scope_label)
        self.btn_check_all = QPushButton("全选")
        self.btn_check_all.setObjectName("Ghost")
        self.btn_check_all.setFixedWidth(56)
        self.btn_check_all.setToolTip("全选当前筛选出的分组（Ctrl+A 等效），可再配合批量隔离")
        self.btn_check_all.clicked.connect(lambda: self.group_table.selectAll())
        self.btn_clear_sel = QPushButton("清空")
        self.btn_clear_sel.setObjectName("Ghost")
        self.btn_clear_sel.setFixedWidth(56)
        self.btn_clear_sel.clicked.connect(lambda: self.group_table.clearSelection())
        head.addWidget(self.btn_check_all)
        head.addWidget(self.btn_clear_sel)
        lay.addLayout(head)

        self.group_table = QTableWidget(0, 5)
        self.group_table.setHorizontalHeaderLabels(["组", "层", "文件", "等级", "可释放"])
        self._setup_table(self.group_table, [90, 60, 60, 80, 90], multi=True)
        self.group_table.itemSelectionChanged.connect(self._on_group_selected)
        lay.addWidget(self.group_table, 1)

        self.btn_batch_q = QPushButton("批量隔离选中组（0 组 / 0 文件）")
        self.btn_batch_q.setObjectName("Danger")
        self.btn_batch_q.setEnabled(False)
        self.btn_batch_q.setToolTip("只处理选中组内的非保留项；执行前会弹出完整清单供逐条核对")
        self.btn_batch_q.clicked.connect(self._batch_quarantine_groups)
        lay.addWidget(self.btn_batch_q)
        return panel

    def _make_dir_panel(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        sec = QLabel("目录筛选  ·  FOLDERS")
        sec.setObjectName("SectionTitle")
        head.addWidget(sec)
        head.addStretch(1)
        self.dir_label = QLabel("未筛选")
        self.dir_label.setObjectName("Subtitle")
        head.addWidget(self.dir_label)
        self.btn_dir_clear = QPushButton("清除")
        self.btn_dir_clear.setObjectName("Ghost")
        self.btn_dir_clear.setFixedWidth(56)
        self.btn_dir_clear.clicked.connect(self._clear_dir_filter)
        head.addWidget(self.btn_dir_clear)
        lay.addLayout(head)

        self.dir_tree = QTreeWidget()
        self.dir_tree.setHeaderLabels(["目录", "组", "文件"])
        self.dir_tree.setAlternatingRowColors(True)
        self.dir_tree.setUniformRowHeights(True)
        self.dir_tree.setTextElideMode(Qt.ElideRight)
        head = self.dir_tree.header()
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        head.setSectionResizeMode(1, QHeaderView.Fixed)
        head.setSectionResizeMode(2, QHeaderView.Fixed)
        self.dir_tree.setColumnWidth(1, 52)
        self.dir_tree.setColumnWidth(2, 58)
        self.dir_tree.itemSelectionChanged.connect(self._on_dir_selected)
        lay.addWidget(self.dir_tree, 1)

        self.btn_dir_q = QPushButton("该目录下批量隔离（0 文件）")
        self.btn_dir_q.setObjectName("Danger")
        self.btn_dir_q.setEnabled(False)
        self.btn_dir_q.setToolTip("选中一个目录，一次性处理该目录（含子目录）下所有组的非保留项")
        self.btn_dir_q.clicked.connect(self._batch_quarantine_dir)
        lay.addWidget(self.btn_dir_q)
        return panel

    @staticmethod
    def _setup_table(table, widths, multi=False):
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(
            QAbstractItemView.ExtendedSelection if multi else QAbstractItemView.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(26)
        table.setShowGrid(False)
        table.setWordWrap(False)
        header = table.horizontalHeader()
        header.setHighlightSections(False)
        for i, width in enumerate(widths):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
            table.setColumnWidth(i, width)
        header.setStretchLastSection(True)

    def _make_player_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_play = QPushButton("▶ 试听选中")
        self.btn_play.setObjectName("Primary")
        self.btn_play.clicked.connect(lambda: self._play_selected())
        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_pause.clicked.connect(lambda: self.player.pause())
        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.clicked.connect(lambda: self.player.stop())
        self.btn_external = QPushButton("系统播放器打开")
        self.btn_external.clicked.connect(self._open_external)
        for btn in (self.btn_play, self.btn_pause, self.btn_stop, self.btn_external):
            bar.addWidget(btn)
        self.now_label = QLabel("未选择音频")
        self.now_label.setObjectName("Subtitle")
        self.now_label.setMinimumWidth(180)
        bar.addWidget(self.now_label)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(self._on_seek_slider)
        bar.addWidget(self.slider, 1)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("Subtitle")
        bar.addWidget(self.time_label)
        bar.addWidget(QLabel("音量"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedWidth(90)
        self.volume.valueChanged.connect(lambda v: self.player.set_volume(v))
        bar.addWidget(self.volume)
        return bar

    # ---------------------------------------------------------------- 异步

    def _init_async(self):
        self.player = Player()
        self.player.position.connect(self._on_position)
        self.player.duration.connect(self._on_duration)
        self.player.failed.connect(lambda msg: self._log(f"内嵌播放器不可用：{msg}（可用「系统播放器打开」）"))
        if not self.player.available:
            self._log("内嵌试听不可用，试听将回退到系统默认播放器")
        self.tasks = TaskRunner()
        self.tasks.output.connect(self._log)
        self.tasks.finished.connect(self._on_task_finished)
        self.peaks_signals = _PeaksSignals()
        self.peaks_signals.done.connect(self._on_peaks)
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(4)

    def _log(self, text):
        self.log_view.appendPlainText(text)
        self.status.showMessage(text[:160])

    # ---------------------------------------------------------------- 数据

    def open_workdir(self, path):
        path = (path or "").strip().strip('"')
        if not path or not os.path.isdir(path):
            QMessageBox.warning(self, "目录无效", "请选择包含 groups.json 或 index.sqlite3 的目录")
            return
        try:
            payload = data.ensure_payload(path, self.root or None)
        except Exception as exc:  # noqa: BLE001 - 外部数据与 Qt 后端异常统一兜底并提示用户
            QMessageBox.critical(self, "打开索引失败", str(exc))
            return
        self.workdir = os.path.abspath(path)
        self.workdir_edit.setText(self.workdir)
        self.payload = payload
        self.root = payload.get("root") or ""
        if not self.qdir:
            self.qdir = data.default_qdir(self.root) if self.root else ""
            self.qdir_label.setText(f"隔离区：{self.qdir}")
        self.groups_all = payload.get("groups", [])
        self._update_stats()
        self._build_dir_tree()
        self._apply_filters()
        self._log(f"已打开索引：{self.workdir}")
        self._log(f"扫描根：{self.root}  ·  L3 边 {payload['summary']['edges']} 条")
        if self.group_table.rowCount() > 0:
            self.group_table.selectRow(0)

    def _update_stats(self):
        if not self.payload:
            return
        s, c = self.payload["summary"], self.payload["counts"]
        self.card_files.set_value(f"{c.get('ok', 0):,}")
        self.card_groups.set_value(f"{s['groups']:,}")
        self.card_reclaim.set_value(data.fmt_size(s["reclaimable_bytes"]))
        self.card_edges.set_value(f"{s['edges']:,}")
        # L3 边为 0 时不抢注意力，有边才上金色
        self.card_edges.set_color(theme.ACCENT if s["edges"] else theme.MUTED)

    def _apply_filters(self):
        if not self.payload:
            return
        layer_idx = self.layer_combo.currentIndex()
        layer = ["", "L1", "L2", "L3"][layer_idx]
        grade = "" if self.grade_combo.currentIndex() == 0 else self.grade_combo.currentText()
        text = self.search_edit.text().strip().lower()
        needle = self._dir_needle()
        result = []
        for g in self.groups_all:
            if layer and g["layer"] != layer:
                continue
            if grade and g["grade"] != grade:
                continue
            if text:
                blob = " ".join([g["id"], g["keep"]] + [f["path"] for f in g["files"]]).lower()
                if text not in blob:
                    continue
            if needle and not any(self._norm(f["path"]).startswith(needle) for f in g["files"]):
                continue
            result.append(g)
        self.groups_view = result
        scope = f"显示 {len(result)} / {len(self.groups_all)} 组"
        if self.dir_filter:
            scope += f"  ·  目录 {os.path.basename(self.dir_filter) or self.dir_filter}"
        self.filter_label.setText(scope)
        self._fill_group_table()

    def _fill_group_table(self):
        self._loading = True
        self.group_table.setRowCount(len(self.groups_view))
        for row, g in enumerate(self.groups_view):
            values = [g["id"], g["layer"], str(g["count"]), g["grade"],
                      data.fmt_size(g["reclaimable_bytes"])]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, g["id"])
                if col in (G_ID, G_COUNT, G_RECLAIM):
                    item.setFont(self._mono_font)
                if col == G_COUNT:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == G_LAYER:
                    item.setForeground(QColor(data.layer_color(g["layer"])))
                if col == G_GRADE:
                    item.setForeground(QColor(data.grade_color(g["grade"])))
                self.group_table.setItem(row, col, item)
        self._loading = False
        self.group_scope_label.setText(f"{len(self.groups_view)} 组")
        self._sync_selection_after_fill()

    def _sync_selection_after_fill(self):
        """筛选重建后把选中标记钉到当前组所在行；当前组已不在结果里则回到首行。

        选择动作在 _loading 下完成，避免重复触发面板重建；只有目标组真的变了才重填。
        """
        if not self.groups_view:
            self._clear_file_panel()
            return
        gid = (self.current_group or {}).get("id")
        row = next((i for i, g in enumerate(self.groups_view) if g["id"] == gid), 0)
        same = self.groups_view[row]["id"] == gid
        self._loading = True
        self.group_table.clearSelection()
        self.group_table.selectRow(row)
        self._loading = False
        if same:
            self._update_batch_button()
        else:
            self._on_group_selected()

    def _clear_file_panel(self):
        self.current_group = None
        self.checked = set()
        self._loading = True
        self.file_table.setRowCount(0)
        self._loading = False
        self.detail_view.clear()
        self.waveform.clear()
        self.wave_scroll.verticalScrollBar().setValue(0)
        self._wave_paths = []
        self.file_scope_label.setText("—")
        self._update_wave_pos()
        self._update_checked_summary()
        self._update_batch_button()

    # ---------------------------------------------------------------- 分组多选

    def _selected_groups(self):
        rows = sorted({idx.row() for idx in self.group_table.selectionModel().selectedRows()})
        return [self.groups_view[r] for r in rows if 0 <= r < len(self.groups_view)]

    @staticmethod
    def _dup_paths_of(groups):
        paths = []
        for g in groups:
            paths.extend(f["path"] for f in g["files"] if not f["keep"])
        return sorted(set(paths))

    def _update_batch_button(self):
        groups = self._selected_groups()
        paths = self._dup_paths_of(groups)
        self.btn_batch_q.setText(f"批量隔离选中组（{len(groups)} 组 / {len(paths)} 文件）")
        self.btn_batch_q.setEnabled(bool(paths))

    def _on_group_selected(self):
        if self._loading:
            return
        groups = self._selected_groups()
        if not groups:
            self._update_batch_button()
            return
        group = groups[0]
        self.current_group = group
        self.checked = {f["path"] for f in group["files"] if not f["keep"]}
        self._fill_file_table(group)
        self._fill_detail(group)
        self._load_waveforms(group)
        self.file_scope_label.setText(
            f"第 1 / {len(groups)} 个选中组  ·  {group['id']}" if len(groups) > 1
            else f"{group['count']} 文件  ·  {group['id']}")
        self._update_checked_summary()
        self._update_batch_button()

    def _fill_file_table(self, group):
        self._loading = True
        files = group["files"]
        self.file_table.setRowCount(len(files))
        for row, f in enumerate(files):
            play = QPushButton("▶")
            play.setObjectName("PlayCell")
            play.setCursor(Qt.PointingHandCursor)
            play.setFocusPolicy(Qt.NoFocus)
            play.setToolTip(f"单独试听：{f['path']}")
            play.clicked.connect(lambda _c=False, path=f["path"]: self._play_path(path, True))
            self.file_table.setCellWidget(row, F_PLAY, play)

            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            check.setCheckState(Qt.Unchecked if f["keep"] else Qt.Checked)
            check.setData(Qt.UserRole, f["path"])
            self.file_table.setItem(row, F_CHECK, check)

            cells = [
                data.short_name(f["path"]),
                data.fmt_size(f["size"]),
                data.fmt_dur(f["duration"]),
                data.fmt_ber(f["ber"]),
                "● 保留" if f["keep"] else "重复项",
                f["path"],
            ]
            for col, value in enumerate(cells, F_NAME):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, f["path"])
                item.setToolTip(f["path"])
                if col in (F_SIZE, F_DUR, F_BER):
                    item.setFont(self._mono_font)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == F_HINT:
                    item.setForeground(QColor(theme.ACCENT if f["keep"] else theme.MUTED))
                self.file_table.setItem(row, col, item)
        self._loading = False
        if files:
            self.file_table.selectRow(0)

    def _fill_detail(self, group):
        lines = [
            f"组 {group['id']}   ·   {group['layer']}   ·   {group['grade']}",
            f"建议保留：{group['keep']}",
            f"组内文件：{group['count']}   ·   可释放：{data.fmt_size(group['reclaimable_bytes'])}",
            "",
            "— 文件清单 —",
        ]
        for f in group["files"]:
            lines.append(
                f"{'保留' if f['keep'] else '重复'}  {data.fmt_size(f['size']):>9}  "
                f"{data.fmt_dur(f['duration']):>8}  BER {data.fmt_ber(f['ber']):>5}  {f['path']}")
        lines.append("")
        if group["edges"]:
            lines.append("— L3 相似边（导出产物） —")
            for e in group["edges"]:
                lines.append(f"{e['grade']}  BER {e['ber']:.4f}  {e['a']}  ↔  {e['b']}")
            lines.append("")
            lines.append("L3 为疑似组，必须人工试听裁决，界面不会自动处置。")
        else:
            lines.append("本组为 L1/L2 确定重复（字节级 / 解码级），不产生相似边。")
        self.detail_view.setPlainText("\n".join(lines))

    def _on_check_changed(self, item):
        if self._loading or item.column() != F_CHECK:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return
        if item.checkState() == Qt.Checked:
            self.checked.add(path)
        else:
            self.checked.discard(path)
        self._update_checked_summary()

    def _update_checked_summary(self):
        size = sum(f["size"] for f in (self.current_group or {}).get("files", [])
                   if f["path"] in self.checked)
        groups = self._selected_groups()
        suffix = "当前组" if len(groups) > 1 else ""
        self.btn_quarantine.setText(f"移入隔离区{suffix}（{len(self.checked)}）")
        self.btn_quarantine.setEnabled(bool(self.checked))
        self.status.showMessage(
            f"当前组 {self.current_group['id'] if self.current_group else '—'}  ·  "
            f"已选 {len(groups)} 组  ·  组内已勾选 {len(self.checked)} 个文件"
            f"（{data.fmt_size(size)}）  ·  源库只读")

    def _select_duplicates(self):
        if not self.current_group:
            return
        self._loading = True
        self.checked = {f["path"] for f in self.current_group["files"] if not f["keep"]}
        for row in range(self.file_table.rowCount()):
            item = self.file_table.item(row, F_CHECK)
            if item:
                item.setCheckState(
                    Qt.Checked if item.data(Qt.UserRole) in self.checked else Qt.Unchecked)
        self._loading = False
        self._update_checked_summary()

    # ---------------------------------------------------------------- 目录树筛选

    @staticmethod
    def _norm(path):
        """统一分隔符与大小写，供前缀比较（Windows 路径不区分大小写）。"""
        return path.replace("/", "\\").lower()

    def _dir_needle(self):
        return (self._norm(self.dir_filter).rstrip("\\") + "\\") if self.dir_filter else ""

    def _path_parts(self, directory):
        """把绝对目录拆成「相对扫描根」的层级片段；库外文件退回盘符起算。"""
        raw = directory.replace("/", "\\")
        anchor = (self.root or "").replace("/", "\\").rstrip("\\")
        if anchor and raw.lower().startswith(anchor.lower()):
            rest = raw[len(anchor):].strip("\\")
            return rest.split("\\") if rest else []
        return [part for part in raw.split("\\") if part]

    def _build_dir_tree(self):
        """由 groups_all 构建目录树：每个节点携带「涉及组数 / 文件数」。"""
        self.dir_tree.blockSignals(True)
        self.dir_tree.clear()
        if not self.groups_all:
            self.dir_tree.blockSignals(False)
            self.dir_label.setText("未筛选")
            return

        root = {"children": {}, "gids": set(), "files": 0, "abs": ""}
        anchor = (self.root or "").replace("/", "\\").rstrip("\\")
        for g in self.groups_all:
            for f in g["files"]:
                parts = self._path_parts(os.path.dirname(f["path"]))
                node = root
                walked = anchor
                for part in parts:
                    walked = f"{walked}\\{part}" if walked else part
                    node = node["children"].setdefault(
                        part, {"children": {}, "gids": set(), "files": 0, "abs": walked})
                node["gids"].add(g["id"])
                node["files"] += 1

        def accumulate(node):
            gids, files = set(node["gids"]), node["files"]
            for child in node["children"].values():
                cg, cf = accumulate(child)
                gids |= cg
                files += cf
            node["gids"], node["files"] = gids, files
            return gids, files

        accumulate(root)

        def insert(parent, node, depth):
            for name in sorted(node["children"], key=str.lower):
                child = node["children"][name]
                item = QTreeWidgetItem([name, str(len(child["gids"])), str(child["files"])])
                item.setData(0, Qt.UserRole, child["abs"])
                item.setToolTip(0, child["abs"])
                item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
                if depth == 0 and child["children"]:
                    item.setExpanded(depth < 1)
                if parent is None:
                    self.dir_tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                insert(item, child, depth + 1)

        insert(None, root, 0)
        self.dir_tree.blockSignals(False)
        self.dir_label.setText(f"{self.dir_tree.topLevelItemCount()} 个顶层目录")
        self._log(f"目录树就绪：{self.dir_tree.topLevelItemCount()} 个顶层节点")

    def _on_dir_selected(self):
        items = self.dir_tree.selectedItems()
        self.dir_filter = items[0].data(0, Qt.UserRole) if items else ""
        if self.dir_filter:
            self.dir_label.setText(self.dir_filter)
            self.dir_label.setToolTip(self.dir_filter)
        else:
            self.dir_label.setText("未筛选")
        self._apply_filters()
        self._update_dir_batch_button()

    def _clear_dir_filter(self):
        self.dir_tree.clearSelection()
        self.dir_filter = ""
        self.dir_label.setText("未筛选")
        self.dir_label.setToolTip("")
        self._apply_filters()
        self._update_dir_batch_button()

    def _dir_dup_paths(self):
        needle = self._dir_needle()
        if not needle:
            return []
        paths = []
        for g in self.groups_all:
            for f in g["files"]:
                if f["keep"]:
                    continue
                if self._norm(f["path"]).startswith(needle):
                    paths.append(f["path"])
        return sorted(set(paths))

    def _update_dir_batch_button(self):
        paths = self._dir_dup_paths()
        self.btn_dir_q.setText(f"该目录下批量隔离（{len(paths)} 文件）")
        self.btn_dir_q.setEnabled(bool(paths))

    # ---------------------------------------------------------------- 波形 / 试听

    def _load_waveforms(self, group):
        """组内每个文件一条轨道：轨道数与文件数一一对应，全部解码，滚动查看。"""
        self._peaks_token += 1
        token = self._peaks_token
        files = group["files"][:WAVE_TRACK_LIMIT]
        self._wave_paths = [f["path"] for f in files]
        self._track_results = [None] * len(self._wave_paths)
        # 先按文件顺序摆好占位轨道，解码完成的再逐个填内容，避免轨道顺序随到达顺序抖动
        self.waveform.set_tracks([
            {"path": f["path"], "label": data.short_name(f["path"]),
             "mins": None, "maxs": None, "duration": f.get("duration") or 0.0,
             "keep": bool(f.get("keep"))}
            for f in files])
        if len(group["files"]) > WAVE_TRACK_LIMIT:
            self._log(f"组内 {len(group['files'])} 个文件，波形只显示前 {WAVE_TRACK_LIMIT} 条")
        for path in self._wave_paths:
            self.pool.start(_PeaksTask(path, self.ffmpeg, token, self.peaks_signals))
        if self._wave_paths:
            self._sync_wave_active()

    def _on_peaks(self, path, token, result):
        if token != self._peaks_token or path not in self._wave_paths:
            return
        idx = self._wave_paths.index(path)
        if result is None:
            self._log(f"波形解码失败（跳过）：{data.short_name(path)}")
            return
        mins, maxs, duration = result
        self._track_results[idx] = {"mins": mins, "maxs": maxs, "duration": duration}
        tracks = self.waveform._tracks
        if 0 <= idx < len(tracks):
            tracks[idx]["mins"] = mins
            tracks[idx]["maxs"] = maxs
            tracks[idx]["duration"] = duration or tracks[idx].get("duration")
            self.waveform.update()

    def _sync_wave_active(self):
        """文件表当前行 → 波形活跃轨；不在视口内就把它滚到中间。"""
        path = self._current_path()
        index = self._wave_paths.index(path) if path in self._wave_paths else -1
        self.waveform.set_active(index)
        self._update_wave_pos()
        if index < 0:
            return
        bar = self.wave_scroll.verticalScrollBar()
        top = PAD_TOP + index * TRACK_H
        view_h = self.wave_scroll.viewport().height()
        if top >= bar.value() and top + TRACK_H <= bar.value() + view_h:
            return  # 已经看得见就不动，避免跟着点选乱跳
        target = top + TRACK_H // 2 - view_h // 2
        bar.setValue(max(0, min(bar.maximum(), target)))

    def _update_wave_pos(self):
        total = self.waveform.track_count()
        index = self.waveform.active()
        self.wave_pos_label.setText(
            f"第 {index + 1} / {total} 条" if index >= 0 and total else f"{total} 条")

    def _select_file_row(self, row):
        """程序性选中文件行：必须显式 scrollTo，selectRow 本身不保证滚动到可见。"""
        if row < 0 or row >= self.file_table.rowCount():
            return
        self.file_table.selectRow(row)
        item = self.file_table.item(row, F_NAME) or self.file_table.item(row, F_PATH)
        if item is not None:
            self.file_table.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    def _on_file_selected(self):
        if self._loading:
            return
        self._sync_wave_active()

    def _on_wave_track_selected(self, index):
        """点波形轨道 → 选中文件表对应行（反向联动）。"""
        if 0 <= index < self.file_table.rowCount() and index != self.file_table.currentRow():
            self._select_file_row(index)

    def _on_wave_track_activated(self, index, seconds):
        """双击波形 → 该文件从该位置试听。"""
        if 0 <= index < self.file_table.rowCount():
            self._select_file_row(index)
            path = self._wave_paths[index] if index < len(self._wave_paths) else ""
            self._play_path(path, True)
            if seconds > 0:
                QTimer.singleShot(120, lambda: self.player.seek(seconds))

    def _on_wave_seek(self, seconds):
        self.player.seek(seconds)
        self.waveform.set_position(seconds)

    def _current_path(self):
        row = self.file_table.currentRow()
        if row >= 0:
            item = self.file_table.item(row, F_PATH)
            if item:
                return item.data(Qt.UserRole) or item.text()
        if self._wave_paths:
            return self._wave_paths[0]
        return ""

    def _play_path(self, path, echo=False):
        if not path:
            return
        if not os.path.isfile(path):
            self._log(f"文件不可达（源盘可能未挂载）：{path}")
            self.status.showMessage(f"文件不可达：{path[:120]}")
            return
        # 试听哪一条就选中哪一条：文件表与波形同步跟着走
        if path in self._wave_paths:
            index = self._wave_paths.index(path)
            if index != self.file_table.currentRow():
                self._select_file_row(index)
        self._current_audio = path
        if self.player.play(path):
            self.now_label.setText(data.short_name(path))
            if echo:
                self._log(f"试听：{path}")
        else:
            self._open_external(path)

    def _play_selected(self):
        self._play_path(self._current_path())

    def _open_external(self, path=None):
        path = path or self._current_path()
        if path and os.path.isfile(path):
            try:
                os.startfile(path)
                self.now_label.setText(f"外部播放：{data.short_name(path)}")
            except OSError as exc:
                self._log(f"外部打开失败：{exc}")

    def _on_position(self, sec):
        if self._duration > 0:
            self.slider.setValue(int(sec / self._duration * 1000))
        self.time_label.setText(f"{_mmss(sec)} / {_mmss(self._duration)}")
        self.waveform.set_position(sec)

    def _on_duration(self, sec):
        if sec > 0:
            self._duration = sec
            self.waveform.set_duration(sec)

    def _on_seek_slider(self, value):
        if self._duration > 0:
            self.player.seek(value / 1000.0 * self._duration)

    # ---------------------------------------------------------------- 任务

    def _ensure_ready(self):
        if not self.workdir:
            QMessageBox.information(self, "先打开索引", "请先选择一个索引工作目录")
            return False
        return True

    def _start_task(self, label, args):
        if self.tasks.running():
            QMessageBox.information(self, "已有任务运行中", "请等当前扫描 / 匹配任务结束后再操作")
            return
        if not self.tasks.start(label, args):
            return
        for btn in (self.btn_scan, self.btn_l3, self.btn_report, self.btn_refresh):
            btn.setEnabled(False)
        self.status.showMessage(f"后台任务进行中：{label}")

    def _on_task_finished(self, code, label):
        for btn in (self.btn_scan, self.btn_l3, self.btn_report, self.btn_refresh):
            btn.setEnabled(True)
        self._log(f"[{label}] {'成功' if code == 0 else '失败'}，刷新数据包")
        self._reload()

    def _run_scan(self):
        if not self._ensure_ready():
            return
        root = self._require_root()
        if not root:
            return
        self._start_task("扫描 L1/L2", ["-m", "audio_dedup.cli", "scan",
                                       "--root", root, "--workdir", self.workdir])

    def _run_l3(self):
        if not self._ensure_ready():
            return
        root = self._require_root()
        if not root:
            return
        self._start_task("L3 感知匹配", ["-m", "audio_dedup.cli", "l3",
                                        "--workdir", self.workdir, "--root", root])

    def _export_report(self):
        if not self._ensure_ready():
            return
        root = self._require_root()
        if not root:
            return
        self._start_task("导出报告", ["-m", "audio_dedup.cli", "report",
                                     "--workdir", self.workdir, "--root", root])

    def _require_root(self):
        if self.root and not self.root.startswith("(见索引)"):
            return self.root
        chosen = QFileDialog.getExistingDirectory(self, "选择被扫描的音效库根（只读）")
        if chosen:
            self.root = chosen
        return self.root if self.root and not self.root.startswith("(见索引)") else ""

    def _reload(self):
        if not self._ensure_ready():
            return
        try:
            payload = data.refresh_payload(self.workdir, self.root or None)
        except Exception as exc:  # noqa: BLE001 - 外部数据与 Qt 后端异常统一兜底并提示用户
            self._log(f"刷新失败：{exc}")
            return
        self.payload = payload
        self.groups_all = payload.get("groups", [])
        self._update_stats()
        self._build_dir_tree()
        self._apply_filters()
        self._log("数据包已刷新：groups.json / edges.csv")

    def _pick_workdir(self):
        chosen = QFileDialog.getExistingDirectory(self, "选择索引工作目录", self.workdir)
        if chosen:
            self.workdir_edit.setText(chosen)

    # ---------------------------------------------------------------- 隔离 / 恢复

    def _quarantine_selected(self):
        """单个组内按勾选处置。"""
        if not self.checked:
            return
        paths = sorted(self.checked)
        total = sum(f["size"] for f in (self.current_group or {}).get("files", [])
                    if f["path"] in self.checked)
        self._run_quarantine(paths, f"当前组 {self.current_group['id'] if self.current_group else '—'}",
                             total)

    def _batch_quarantine_groups(self):
        """选中分组批量处置：把所选组内全部非保留项一次性隔离。"""
        groups = self._selected_groups()
        if not groups:
            return
        paths = self._dup_paths_of(groups)
        if not paths:
            QMessageBox.information(self, "无可处置文件", "所选组的重复项为空")
            return
        size = sum(f["size"] for g in groups for f in g["files"] if not f["keep"])
        self._run_quarantine(paths, f"{len(groups)} 组批量", size)

    def _batch_quarantine_dir(self):
        """目录维度批量处置：把该目录（含子目录）下所有组的非保留项一次性隔离。"""
        paths = self._dir_dup_paths()
        if not paths:
            return
        size = sum(f["size"] for g in self.groups_all for f in g["files"]
                   if not f["keep"] and self._norm(f["path"]).startswith(self._dir_needle()))
        self._run_quarantine(paths, f"目录 {self.dir_filter}", size)

    def _run_quarantine(self, paths, headline, total_size):
        """统一入口：完整清单 + 目录确认 + 大批量二次关卡。"""
        paths = sorted(set(paths))
        if not paths:
            return
        bulk = len(paths) >= BULK_CONFIRM_THRESHOLD
        dlg = QDialog(self)
        dlg.setWindowTitle("确认移入隔离区")
        dlg.resize(820, 580)
        lay = QVBoxLayout(dlg)
        warn = QLabel(
            f"{headline}\n"
            f"即将把 {len(paths)} 个文件移入隔离区（{data.fmt_size(total_size)}）。\n"
            "动作＝同盘 rename，按 manifest 可一键恢复；不删除任何文件。")
        warn.setWordWrap(True)
        warn.setStyleSheet(f"color: {theme.HIGH}; font-weight: 600;")
        lay.addWidget(warn)
        qrow = QHBoxLayout()
        qrow.addWidget(QLabel("隔离目录"))
        qedit = QLineEdit(self.qdir)
        qrow.addWidget(qedit, 1)
        pick = QPushButton("更改…")
        pick.clicked.connect(lambda: qedit.setText(
            QFileDialog.getExistingDirectory(self, "选择隔离目录", qedit.text()) or qedit.text()))
        qrow.addWidget(pick)
        lay.addLayout(qrow)
        listing = QPlainTextEdit()
        listing.setReadOnly(True)
        listing.setPlainText("\n".join(paths))
        lay.addWidget(listing, 1)
        gate = None
        if bulk:
            gate = QCheckBox(
                f"我已逐条核对上述 {len(paths)} 个路径，确认其中不含需要保留的文件")
            lay.addWidget(gate)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(dlg.reject)
        confirm = QPushButton("确认移入隔离区")
        confirm.setObjectName("Danger")
        confirm.clicked.connect(dlg.accept)
        if gate is not None:
            confirm.setEnabled(False)
            gate.toggled.connect(confirm.setEnabled)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        lay.addLayout(buttons)
        if dlg.exec() != QDialog.Accepted:
            self._log(f"隔离已取消（{headline}）")
            return
        qdir = qedit.text().strip()
        if not qdir:
            return
        self.qdir = qdir
        self.qdir_label.setText(f"隔离区：{qdir}")
        root = self._require_root()
        if not root:
            return
        try:
            batch = quarantine.quarantine_files(paths, qdir, root)
        except quarantine.QuarantineError as exc:
            QMessageBox.critical(self, "隔离失败", str(exc))
            self._log(f"隔离失败：{exc}")
            return
        data.mark_quarantined(self.workdir, paths)
        self.player.stop()
        self._log(f"隔离完成：批次 {batch['id']}，{len(paths)} 个文件（{headline}），"
                  f"清单 {qdir}/manifest.json")
        QMessageBox.information(self, "隔离完成",
                                f"已移入 {len(paths)} 个文件，批次 {batch['id']}。\n"
                                "可用「恢复批次」一键还原。")
        self.checked = set()
        self._reload()

    def _restore_batch(self):
        if not self.qdir:
            QMessageBox.information(self, "未设置隔离区", "请先执行一次隔离，或指定隔离目录")
            return
        batches = data.manifest_batches(self.qdir)
        if not batches:
            QMessageBox.information(self, "无批次", f"隔离目录内没有 manifest 批次：{self.qdir}")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("恢复隔离批次")
        dlg.resize(700, 400)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("选择要恢复的批次（恢复前逐个核验 SHA256，原位已有文件则拒绝覆盖）"))
        listing = QListWidget()
        for b in reversed(batches):
            done = len(b.get("restored", []))
            listing.addItem(f"{b['id']}  ·  {len(b['files'])} 文件  ·  已恢复 {done}  ·  {b.get('time', '')}")
        listing.setCurrentRow(0)
        lay.addWidget(listing, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(dlg.reject)
        confirm = QPushButton("恢复选中批次")
        confirm.setObjectName("Primary")
        confirm.clicked.connect(dlg.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        lay.addLayout(buttons)
        if dlg.exec() != QDialog.Accepted:
            return
        selected = list(reversed(batches))[listing.currentRow()]
        try:
            restored = quarantine.restore_files(self.qdir, selected["id"])
        except quarantine.QuarantineError as exc:
            QMessageBox.critical(self, "恢复失败", str(exc))
            self._log(f"恢复失败：{exc}")
            return
        data.mark_restored(self.workdir, restored)
        self._log(f"恢复完成：批次 {selected['id']}，{len(restored)} 个文件")
        QMessageBox.information(self, "恢复完成", f"已恢复 {len(restored)} 个文件，SHA256 往返核验通过。")
        self._reload()


def _capture(window, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    pix = window.grab()
    ok = pix.save(path)
    print(f"SCREENSHOT {'OK' if ok else 'FAIL'} {path} {pix.width()}x{pix.height()}", flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="audio-dedup-gui", description="音频重复识别工具 GUI")
    parser.add_argument("--workdir", default=DEFAULT_WORKDIR, help="索引工作目录")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--auto-screenshot", default=None, help="延时 4 秒后把窗口保存为 PNG")
    parser.add_argument("--auto-quit", type=int, default=0, help="毫秒后自动退出（冒烟测试用）")
    args, _unknown = parser.parse_known_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyleSheet(theme.QSS)
    icon = _icon_path()
    if icon:
        app.setWindowIcon(QIcon(icon))
    window = MainWindow(args.workdir or None, args.ffmpeg)
    window.show()
    if args.auto_screenshot:
        QTimer.singleShot(4000, lambda: _capture(window, args.auto_screenshot))
    if args.auto_quit:
        QTimer.singleShot(args.auto_quit, app.quit)
    return app.exec()
