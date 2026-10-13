"""The audio level meter widget: one vertical bar per channel, PPM ballistics, dBFS scale.

Reading it: the wide bar is the programme peak level (instant attack, slow fall) coloured
by zone, green up to the EBU alignment level (-18 dBFS), amber up to the maximum permitted
level (-9 dBFS), red above. The narrow pale bar inside it is RMS, the white line is the
peak-hold marker, and the number above each bar is the held peak in dBFS. "OVER" lights
when a sample reaches full scale.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme
from .levels import ALIGNMENT_DB, MAX_DB, MAX_PERMITTED_DB, MIN_DB, ChannelState, format_db

BAR_W = 14
GAP = 5
SCALE_W = 30
TOP_PAD = 18
BOTTOM_PAD = 16
LEFT_PAD = 4
TICKS = [0, -3, -6, -9, -12, -15, -18, -21, -24, -27, -30, -40, -50, -60]
LABELS_ALL = {0, -6, -12, -18, -24, -30, -40, -50, -60}
LABELS_FEW = {0, -12, -18, -30, -60}


def zone_color(db: float) -> QColor:
    if db >= MAX_PERMITTED_DB:
        return QColor(theme.RED)
    if db >= ALIGNMENT_DB:
        return QColor(theme.AMBER)
    return QColor(theme.GREEN)


class LevelMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._states: list[ChannelState] = []
        self._labels: list[str] = []
        self._has_audio = False
        self._over = False
        self._dim = True
        self._font = QFont()
        self._font.setPointSizeF(7.5)
        self._font_small = QFont()
        self._font_small.setPointSizeF(6.5)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumHeight(90)
        self.setToolTip("Wide bar: peak level (dBFS).  Inner pale bar: RMS.  White line: peak hold.\n"
                        "Green ≤ −18 dBFS (alignment), amber to −9 dBFS (max permitted), red above.")

    # ------------------------------------------------------------------ data in

    def set_levels(self, states: list[ChannelState], labels: list[str], has_audio: bool, over: bool) -> None:
        resize = len(states) != len(self._states)
        self._states = list(states)
        self._labels = list(labels)
        self._has_audio = has_audio
        self._over = over
        if resize:
            self.updateGeometry()
        self.update()

    def set_dim(self, dim: bool) -> None:
        if dim != self._dim:
            self._dim = dim
            self.update()

    # ------------------------------------------------------------------ geometry

    def _bar_count(self) -> int:
        return max(2, len(self._states))

    def sizeHint(self) -> QSize:
        return QSize(LEFT_PAD + self._bar_count() * (BAR_W + GAP) + SCALE_W, 220)

    def minimumSizeHint(self) -> QSize:
        return QSize(self.sizeHint().width(), 90)

    @staticmethod
    def _y(db: float, top: float, height: float) -> float:
        db = max(MIN_DB, min(MAX_DB, db))
        return top + (MAX_DB - db) / (MAX_DB - MIN_DB) * height

    # ------------------------------------------------------------------ painting

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        w, h_total = self.width(), self.height()
        p.fillRect(0, 0, w, h_total, QColor(theme.PANEL))

        top = TOP_PAD
        bottom = h_total - BOTTOM_PAD
        h = max(1.0, bottom - top)
        n = self._bar_count()
        alpha = 255 if (self._has_audio and not self._dim) else 90
        muted = QColor(theme.MUTED)

        for i in range(n):
            x = LEFT_PAD + i * (BAR_W + GAP)
            p.fillRect(QRectF(x, top, BAR_W, h), QColor(theme.TRACK))
            st = self._states[i] if i < len(self._states) else None
            if st is not None and self._has_audio:
                self._fill_zones(p, x, top, h, st.peak, alpha)
                y_rms = self._y(st.rms, top, h)
                p.fillRect(QRectF(x + 4, y_rms, BAR_W - 8, bottom - y_rms), QColor(255, 255, 255, 70))
                if st.hold > MIN_DB:
                    y_hold = self._y(st.hold, top, h)
                    c = QColor("#ffffff") if st.hold < MAX_PERMITTED_DB else QColor(theme.RED).lighter(130)
                    c.setAlpha(alpha)
                    p.fillRect(QRectF(x, y_hold - 1, BAR_W, 2), c)
                # held peak readout above the bar
                p.setFont(self._font_small)
                c = zone_color(st.hold)
                c.setAlpha(alpha)
                p.setPen(c)
                txt = format_db(st.hold, 0) if st.hold > MIN_DB else "–"
                p.drawText(QRectF(x - GAP / 2, 2, BAR_W + GAP, TOP_PAD - 4), Qt.AlignCenter, txt)
            # channel label under the bar
            p.setFont(self._font_small)
            p.setPen(muted)
            label = self._labels[i] if i < len(self._labels) else ("L" if i == 0 and n == 2 else "R" if n == 2 else str(i + 1))
            p.drawText(QRectF(x - GAP / 2, bottom + 2, BAR_W + GAP, BOTTOM_PAD - 2), Qt.AlignCenter, label)

        bars_right = LEFT_PAD + n * (BAR_W + GAP) - GAP

        # reference lines across the bars: alignment and maximum permitted level
        for db, col in ((ALIGNMENT_DB, QColor(theme.AMBER)), (MAX_PERMITTED_DB, QColor(theme.RED))):
            col.setAlpha(150)
            pen = QPen(col, 1, Qt.DashLine)
            p.setPen(pen)
            y = self._y(db, top, h)
            p.drawLine(QRectF(LEFT_PAD, y, 0, 0).topLeft(), QRectF(bars_right, y, 0, 0).topLeft())

        # scale
        x_s = bars_right + 3
        p.setFont(self._font_small)
        px_per_db = h / (MAX_DB - MIN_DB)
        labels = LABELS_ALL if px_per_db * 6 >= 11 else LABELS_FEW
        for db in TICKS:
            y = self._y(db, top, h)
            p.setPen(QPen(muted, 1))
            p.drawLine(QRectF(x_s, y, 0, 0).topLeft(), QRectF(x_s + 3, y, 0, 0).topLeft())
            if db in labels:
                p.drawText(QRectF(x_s + 6, y - 6, SCALE_W - 6, 12), Qt.AlignLeft | Qt.AlignVCenter, str(abs(db)))

        if self._over and self._has_audio:
            p.setFont(self._font)
            p.setPen(QColor(theme.RED))
            p.fillRect(QRectF(x_s + 3, 2, SCALE_W - 4, TOP_PAD - 5), QColor(theme.RED).darker(300))
            p.drawText(QRectF(x_s + 3, 2, SCALE_W - 4, TOP_PAD - 5), Qt.AlignCenter, "OVER")

        if not self._has_audio:
            p.save()
            p.setPen(muted)
            p.setFont(self._font)
            p.translate(LEFT_PAD + (bars_right - LEFT_PAD) / 2, top + h / 2)
            p.rotate(-90)
            p.drawText(QRectF(-h / 2, -8, h, 16), Qt.AlignCenter, "no audio" if self._dim is False else "")
            p.restore()
        p.end()

    def _fill_zones(self, p: QPainter, x: float, top: float, h: float, level: float, alpha: int) -> None:
        y_level = self._y(level, top, h)
        zones = ((MIN_DB, ALIGNMENT_DB, QColor(theme.GREEN)),
                 (ALIGNMENT_DB, MAX_PERMITTED_DB, QColor(theme.AMBER)),
                 (MAX_PERMITTED_DB, MAX_DB, QColor(theme.RED)))
        for lo, hi, col in zones:
            seg_top = self._y(hi, top, h)
            seg_bottom = self._y(lo, top, h)
            visible_top = max(seg_top, y_level)
            if visible_top < seg_bottom:
                col.setAlpha(alpha)
                p.fillRect(QRectF(x, visible_top, BAR_W, seg_bottom - visible_top), col)
