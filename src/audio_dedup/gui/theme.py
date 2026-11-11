"""GUI 深色主题：单一 QSS 真源，配色常量供波形等自绘控件复用。

视觉口径（对齐 SFX Tools 工业工作台）：深色底、灰阶层次、单一暖金强调、
中文正文用雅黑、数值与路径用等宽字体。层级色收敛为「灰阶递进 + 只有 L3 上色」，
颜色只用来表达「需要人注意」，不用来装饰。
"""

BG = "#0d1015"
PANEL = "#14181f"
PANEL2 = "#1a1f28"
PANEL3 = "#20262f"
BORDER = "#242a34"
BORDER2 = "#333b47"
TEXT = "#dfe6f0"
TEXT_DIM = "#97a3b6"
MUTED = "#6b7788"
FAINT = "#4d5764"

ACCENT = "#d9a441"
ACCENT_DIM = "#a87c2c"
ACCENT_SOFT = "#3a2f1c"

L1 = "#dfe6f0"
L2 = "#9aa9bd"
L3 = "#d9a441"

HIGH = "#d9a441"
MID = "#a8823f"
LOW = "#7d8a9d"

DANGER = "#c0554f"
DANGER_DIM = "#7d3a37"
OK = "#7f9e73"

TRACK_ACTIVE = "#e3b45a"
TRACK_IDLE = "#8d7a55"

UI_FONT = '"Microsoft YaHei UI", "Segoe UI", sans-serif'
MONO_FONT = '"Consolas", "Cascadia Mono", monospace'

QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: {UI_FONT};
    font-size: 13px;
}}
QLabel {{ background: transparent; }}
QMainWindow, QDialog {{ background: {BG}; }}

QFrame#Card {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QFrame#Topbar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}

QLabel#Title {{ font-size: 15px; font-weight: 600; color: {TEXT}; letter-spacing: 0.3px; }}
QLabel#Subtitle {{ color: {MUTED}; font-size: 11px; }}
QLabel#Badge {{
    background: {PANEL2}; color: {TEXT_DIM};
    border: 1px solid {BORDER2}; border-radius: 9px;
    padding: 3px 10px; font-size: 11px;
}}
QLabel#StatValue {{
    font-family: {MONO_FONT}; font-size: 20px; font-weight: 600; color: {TEXT};
}}
QLabel#StatLabel {{ color: {MUTED}; font-size: 11px; }}
QLabel#SectionTitle {{
    color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1.2px;
}}

QLineEdit, QComboBox {{
    background: {PANEL2}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 4px;
    padding: 7px 9px; selection-background-color: {ACCENT_SOFT};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT_DIM}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {PANEL2}; color: {TEXT};
    selection-background-color: {ACCENT_SOFT}; border: 1px solid {BORDER2};
    outline: 0;
}}

QPushButton {{
    background: {PANEL2}; color: {TEXT_DIM};
    border: 1px solid {BORDER2}; border-radius: 4px;
    padding: 7px 14px; font-weight: 500;
}}
QPushButton:hover {{ background: {PANEL3}; color: {TEXT}; border-color: #414b59; }}
QPushButton:pressed {{ background: {PANEL}; }}
QPushButton:disabled {{ color: {FAINT}; border-color: {BORDER}; background: {PANEL}; }}
QPushButton#Primary {{ background: {ACCENT_SOFT}; border-color: {ACCENT_DIM}; color: {ACCENT}; }}
QPushButton#Primary:hover {{ background: #463820; color: #f0c66a; }}
QPushButton#Primary:disabled {{ background: {PANEL}; border-color: {BORDER}; color: {FAINT}; }}
QPushButton#Danger {{ background: transparent; border-color: {DANGER_DIM}; color: {DANGER}; }}
QPushButton#Danger:hover {{ background: #2a1a1a; border-color: {DANGER}; }}
QPushButton#Danger:disabled {{ background: transparent; border-color: {BORDER}; color: {FAINT}; }}
QPushButton#Ghost {{ background: transparent; border-color: transparent; color: {MUTED}; padding: 4px 8px; }}
QPushButton#Ghost:hover {{ color: {TEXT}; background: {PANEL2}; }}
QPushButton#PlayCell {{
    background: transparent; color: {MUTED};
    border: none; padding: 0; font-size: 13px;
}}
QPushButton#PlayCell:hover {{ color: {ACCENT}; }}
QPushButton#PlayCell:disabled {{ color: {FAINT}; }}

QTableWidget, QTableView, QTreeWidget {{
    background: {PANEL}; alternate-background-color: #171c24;
    color: {TEXT}; gridline-color: {BORDER};
    border: 1px solid {BORDER}; border-radius: 4px;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT};
    outline: 0;
}}
QTableWidget::item {{ padding: 3px 6px; border: none; }}
QTableWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QTreeWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QTreeWidget::branch {{ background: transparent; }}
QHeaderView::section {{
    background: {BG}; color: {MUTED};
    border: none; border-right: 1px solid {BORDER}; border-bottom: 1px solid {BORDER};
    padding: 7px 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.4px;
}}
QHeaderView::section:hover {{ color: {TEXT_DIM}; }}

QPlainTextEdit, QTextEdit {{
    background: #10141a; color: #9aa7b8;
    border: 1px solid {BORDER}; border-radius: 4px;
    font-family: {MONO_FONT}; font-size: 11px;
}}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 4px; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {MUTED};
    padding: 7px 16px; border: none; border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT_DIM}; }}
QTabBar::tab:hover {{ color: {TEXT_DIM}; }}

QSlider::groove:horizontal {{ background: {PANEL3}; height: 3px; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {TEXT_DIM}; width: 10px; margin: -5px 0; border-radius: 5px;
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT}; }}
QSlider::sub-page:horizontal {{ background: {ACCENT_DIM}; border-radius: 2px; }}

QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #333b47; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #46505f; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #333b47; border-radius: 4px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{ background: {PANEL}; color: {MUTED}; border-top: 1px solid {BORDER}; font-size: 11px; }}
QStatusBar::item {{ border: none; }}
QCheckBox {{ color: {TEXT_DIM}; spacing: 7px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 3px;
    border: 1px solid {BORDER2}; background: {PANEL2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT_DIM}; border-color: {ACCENT}; }}
QToolTip {{
    background: {PANEL3}; color: {TEXT}; border: 1px solid {BORDER2};
    padding: 5px 8px; font-size: 11px;
}}
QMessageBox {{ background: {PANEL}; }}
QScrollArea {{ border: none; background: transparent; }}
"""
