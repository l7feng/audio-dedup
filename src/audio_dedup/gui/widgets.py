"""自绘控件：多轨波形对比、统计卡片。

波形口径对齐 SFX Tools：真实峰值做镜像包络填充（不画竖线森林、不用彩虹色），
一轨对应组内一个文件，单一强调色 + 活跃轨高亮；轨道数与文件数一一对应，超出滚动。
"""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme

LABEL_W = 238       # 左侧标签列宽
TRACK_H = 34        # 单轨高度（压低以在一屏内容纳更多轨道）
PAD_TOP = 24        # 顶部留出时间刻度
PAD_BOTTOM = 10


class StatCard(QFrame):
    """顶栏统计卡片：数值 + 说明，可指定数值颜色。"""

    def __init__(self, label: str, color: str = theme.TEXT, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(148)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(1)
        self.value = QLabel("—")
        self.value.setObjectName("StatValue")
        self.value.setStyleSheet(f"color: {color};")
        self.caption = QLabel(label)
        self.caption.setObjectName("StatLabel")
        lay.addWidget(self.value)
        lay.addWidget(self.caption)

    def set_value(self, text: str):
        self.value.setText(text)

    def set_color(self, color: str):
        self.value.setStyleSheet(f"color: {color};")


class WaveformWidget(QWidget):
    """多轨波形：镜像包络、单色、活跃轨高亮、点击定位。

    tracks: [{"path", "label", "mins", "maxs", "duration", "keep"}]
    active: 当前与文件表选中行对应的轨道下标（-1 表示无）

    交互约定：
    - 单击左侧标签区 = 选中该文件（不发 seek）
    - 单击波形区 = 选中该文件并从点击位置定位
    - 双击任意位置 = 从该位置试听该文件
    """

    seekRequested = Signal(float)
    trackSelected = Signal(int)
    trackActivated = Signal(int, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Waveform")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self._tracks = []
        self._active = -1
        self._position = 0.0
        self._duration = 0.0
        self._hover_x = -1.0
        self.setMinimumHeight(TRACK_H * 2)

    # ------------------------------------------------------------------ 数据

    def set_tracks(self, tracks: list):
        self._tracks = list(tracks)
        self._active = -1
        self._duration = max((t.get("duration") or 0.0 for t in self._tracks), default=0.0)
        self._relayout()

    def set_active(self, index: int):
        index = index if 0 <= index < len(self._tracks) else -1
        if index != self._active:
            self._active = index
            self.update()

    def active(self) -> int:
        return self._active

    def set_duration(self, duration: float):
        if duration and duration > 0:
            self._duration = float(duration)
            self.update()

    def set_position(self, seconds: float):
        self._position = max(0.0, float(seconds))
        self.update()

    def clear(self):
        self._tracks = []
        self._active = -1
        self._position = 0.0
        self._duration = 0.0
        self._relayout()

    def track_count(self) -> int:
        return len(self._tracks)

    def _relayout(self):
        need = PAD_TOP + max(1, len(self._tracks)) * TRACK_H + PAD_BOTTOM
        self.setMinimumHeight(need)
        self.setFixedHeight(need)
        self.update()

    # ------------------------------------------------------------------ 几何

    def _plot_left(self) -> float:
        return LABEL_W

    def _plot_rect(self) -> QRectF:
        left = self._plot_left()
        return QRectF(left, PAD_TOP,
                      max(20.0, self.width() - left - 14),
                      max(20.0, len(self._tracks) * TRACK_H))

    def _track_rect(self, index: int) -> QRectF:
        r = self._plot_rect()
        return QRectF(r.left(), r.top() + index * TRACK_H, r.width(), TRACK_H)

    def _x_of(self, seconds: float) -> float:
        r = self._plot_rect()
        if self._duration <= 0:
            return r.left()
        return r.left() + min(1.0, max(0.0, seconds / self._duration)) * r.width()

    def _index_at(self, y: float) -> int:
        r = self._plot_rect()
        if not self._tracks or y < r.top():
            return -1
        idx = int((y - r.top()) // TRACK_H)
        return idx if 0 <= idx < len(self._tracks) else -1

    def _seconds_at(self, x: float) -> float:
        r = self._plot_rect()
        if r.width() <= 0 or self._duration <= 0:
            return 0.0
        return max(0.0, min(1.0, (x - r.left()) / r.width())) * self._duration

    # ------------------------------------------------------------------ 交互

    def mouseMoveEvent(self, event):
        self._hover_x = event.position().x()
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_x = -1.0
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        idx = self._index_at(pos.y())
        if idx < 0:
            return
        self.trackSelected.emit(idx)
        if pos.x() >= self._plot_left():
            sec = self._seconds_at(pos.x())
            self.set_position(sec)
            self.seekRequested.emit(sec)

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        idx = self._index_at(pos.y())
        if idx < 0:
            return
        sec = self._seconds_at(pos.x()) if pos.x() >= self._plot_left() else 0.0
        self.trackActivated.emit(idx, sec)

    # ------------------------------------------------------------------ 绘制

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#10141a"))

        if not self._tracks:
            p.setPen(QColor(theme.MUTED))
            f = QFont()
            f.setPointSize(9)
            p.setFont(f)
            p.drawText(QRectF(0, 0, self.width(), 80), Qt.AlignCenter,
                       "选中一个分组后，这里按组内文件逐条显示波形")
            p.end()
            return

        r = self._plot_rect()
        head_font = QFont()
        head_font.setPointSize(8)
        mono = QFont("Consolas")
        mono.setPointSize(8)

        # 顶部时间刻度（跟随内容滚动，多数时候停在顶部）
        if self._duration > 0:
            p.setFont(mono)
            fm = QFontMetrics(mono)
            p.setPen(QColor(theme.MUTED))
            for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                x = r.left() + frac * r.width()
                text = _tick(frac * self._duration, self._duration)
                w = fm.horizontalAdvance(text)
                if frac == 0.0:
                    p.drawText(QRectF(x, 4, w + 4, 14), Qt.AlignLeft | Qt.AlignVCenter, text)
                elif frac == 1.0:
                    p.drawText(QRectF(x - w - 4, 4, w + 4, 14),
                               Qt.AlignRight | Qt.AlignVCenter, text)
                else:
                    p.drawText(QRectF(x - w / 2, 4, w, 14), Qt.AlignCenter, text)

        # 竖向极淡网格
        p.setPen(QPen(QColor("#1c232c"), 1, Qt.DashLine))
        for frac in (0.25, 0.5, 0.75):
            x = r.left() + frac * r.width()
            p.drawLine(int(x), int(r.top()), int(x), int(r.bottom()))

        for i, t in enumerate(self._tracks):
            band = self._track_rect(i)
            active = i == self._active
            keep = bool(t.get("keep"))
            if active:
                p.fillRect(QRectF(0, band.top(), self.width(), TRACK_H), QColor("#1f2733"))
                p.setPen(QPen(QColor("#2f3946"), 1))
                p.drawLine(QPointF(0, band.top()), QPointF(self.width(), band.top()))
                p.drawLine(QPointF(0, band.bottom()), QPointF(self.width(), band.bottom()))
                p.fillRect(QRectF(0, band.top(), 4, TRACK_H), QColor(theme.ACCENT))

            color = QColor(theme.TRACK_ACTIVE if active else theme.TRACK_IDLE)

            # 序号（活跃轨前加指针）
            p.setFont(mono)
            p.setPen(QColor(theme.ACCENT if active else theme.MUTED))
            p.drawText(QRectF(14, band.top(), 20, TRACK_H),
                       Qt.AlignVCenter | Qt.AlignLeft, f"{i + 1:02d}")

            # 保留项：文件名前的金色圆点
            if keep:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.ACCENT_DIM))
                p.drawEllipse(QPointF(40, band.center().y()), 2.5, 2.5)
                p.setBrush(Qt.NoBrush)

            # 文件名
            p.setFont(head_font)
            label = t.get("label", "")
            fm = QFontMetrics(head_font)
            left = 46 if keep else 40
            avail = LABEL_W - left - 48
            p.setPen(QColor(theme.TEXT if (active or keep) else theme.TEXT_DIM))
            p.drawText(QRectF(left, band.top(), avail, TRACK_H),
                       Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(label, Qt.ElideMiddle, avail))

            # 时长
            p.setFont(mono)
            p.setPen(QColor(theme.ACCENT if active else theme.MUTED))
            p.drawText(QRectF(LABEL_W - 54, band.top(), 44, TRACK_H),
                       Qt.AlignVCenter | Qt.AlignRight, _dur(t.get("duration")))

            mins, maxs = t.get("mins"), t.get("maxs")
            if mins is None or maxs is None or len(mins) == 0 or len(maxs) == 0:
                p.setPen(QColor(theme.FAINT))
                p.setFont(head_font)
                p.drawText(band, Qt.AlignCenter, "波形解码失败")
                continue
            self._draw_envelope(p, band, mins, maxs, color, active)

            p.setPen(QPen(QColor("#1b222b"), 1))
            p.drawLine(QPointF(band.left(), band.bottom()),
                       QPointF(band.right(), band.bottom()))

        if r.left() <= self._hover_x < r.right():
            p.setPen(QPen(QColor("#3d4757"), 1, Qt.DashLine))
            p.drawLine(QPointF(self._hover_x, r.top()), QPointF(self._hover_x, r.bottom()))

        if self._duration > 0:
            x = self._x_of(self._position)
            p.setPen(QPen(QColor(theme.ACCENT), 1))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setBrush(QColor(theme.ACCENT))
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([
                QPointF(x - 4, r.top() - 6), QPointF(x + 4, r.top() - 6), QPointF(x, r.top())]))
        p.end()

    def _draw_envelope(self, p, band: QRectF, mins, maxs, color: QColor, active: bool):
        """真实峰值镜像包络：上沿取 max、下沿取 min，闭合成填充多边形。"""
        count = min(len(mins), len(maxs))
        if count < 2:
            return
        center = band.center().y()
        amp = band.height() / 2 - 6
        top, bottom = [], []
        for j in range(count):
            x = band.left() + (j / (count - 1)) * band.width()
            hi = max(-1.0, min(1.0, float(maxs[j])))
            lo = max(-1.0, min(1.0, float(mins[j])))
            top.append(QPointF(x, center - hi * amp))
            bottom.append(QPointF(x, center - lo * amp))
        poly = QPolygonF(top + list(reversed(bottom)))
        fill = QColor(color)
        fill.setAlpha(200 if active else 105)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawPolygon(poly)
        # 上包络描边：形状在满幅素材上也能看出起伏
        stroke = QColor(color)
        stroke.setAlpha(170 if active else 80)
        p.setPen(QPen(stroke, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(top))
        p.setPen(QPen(QColor("#252c36"), 1))
        p.drawLine(QPointF(band.left(), center), QPointF(band.right(), center))


def _dur(seconds) -> str:
    try:
        value = float(seconds or 0)
    except (TypeError, ValueError):
        return "—"
    if value <= 0:
        return "—"
    return f"{value:.1f}s" if value < 10 else f"{value:.0f}s"


def _mmss(seconds: float) -> str:
    sec = max(0.0, float(seconds or 0))
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


def _tick(seconds: float, total: float) -> str:
    """短素材用秒（保留一位小数），长素材用 m:ss，避免 0.6 秒的文件全显示 0:00。"""
    if total < 10:
        return f"{seconds:.1f}s"
    if total < 60:
        return f"{seconds:.1f}s"
    return _mmss(seconds)
