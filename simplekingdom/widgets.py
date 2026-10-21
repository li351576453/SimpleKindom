"""界面中的自绘小组件与图标。"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import QWidget

from .hexmath import world_bounds


def make_color_icon(color: str, size: int = 26, ring: bool = False) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    c = QColor(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(3, 3, size - 6, size - 6), 6, 6)
    if ring:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 150), 1.5))
        p.drawRoundedRect(QRectF(3.5, 3.5, size - 7, size - 7), 6, 6)
    p.end()
    return QIcon(pm)


def make_icon(kind: str, color: str = "#e6ddc9", size: int = 22) -> QIcon:
    """用线条绘制一组简洁的工具图标，避免外部资源依赖。"""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color), 1.65)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = float(size)
    if kind == "new":
        p.drawLine(QPointF(s / 2, s * 0.24), QPointF(s / 2, s * 0.76))
        p.drawLine(QPointF(s * 0.24, s / 2), QPointF(s * 0.76, s / 2))
    elif kind == "open":
        path = QPainterPath()
        path.moveTo(s * 0.16, s * 0.36)
        path.lineTo(s * 0.42, s * 0.36)
        path.lineTo(s * 0.50, s * 0.45)
        path.lineTo(s * 0.84, s * 0.45)
        path.lineTo(s * 0.78, s * 0.78)
        path.lineTo(s * 0.18, s * 0.78)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "save":
        p.drawRoundedRect(QRectF(s * 0.22, s * 0.22, s * 0.56, s * 0.56), 2, 2)
        p.drawLine(QPointF(s * 0.50, s * 0.18), QPointF(s * 0.50, s * 0.56))
        p.drawLine(QPointF(s * 0.34, s * 0.42), QPointF(s * 0.50, s * 0.58))
        p.drawLine(QPointF(s * 0.66, s * 0.42), QPointF(s * 0.50, s * 0.58))
    elif kind == "export":
        p.drawRoundedRect(QRectF(s * 0.18, s * 0.20, s * 0.64, s * 0.60), 3, 3)
        p.drawEllipse(QPointF(s * 0.38, s * 0.38), s * 0.06, s * 0.06)
        path = QPainterPath()
        path.moveTo(s * 0.22, s * 0.68)
        path.lineTo(s * 0.43, s * 0.48)
        path.lineTo(s * 0.58, s * 0.62)
        path.lineTo(s * 0.70, s * 0.51)
        path.lineTo(s * 0.79, s * 0.68)
        p.drawPath(path)
    elif kind in ("undo", "redo"):
        p.save()
        if kind == "redo":
            p.translate(s, 0)
            p.scale(-1, 1)
        path = QPainterPath()
        path.arcMoveTo(QRectF(s * 0.24, s * 0.26, s * 0.52, s * 0.48), 135)
        path.arcTo(QRectF(s * 0.24, s * 0.26, s * 0.52, s * 0.48), 135, -210)
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.20, s * 0.31), QPointF(s * 0.30, s * 0.53))
        p.drawLine(QPointF(s * 0.19, s * 0.31), QPointF(s * 0.40, s * 0.28))
        p.restore()
    elif kind == "fit":
        for x, y, dx, dy in (
            (0.18, 0.18, 0.14, 0.14),
            (0.82, 0.18, -0.14, 0.14),
            (0.18, 0.82, 0.14, -0.14),
            (0.82, 0.82, -0.14, -0.14),
        ):
            p.drawLine(QPointF(s * x, s * y), QPointF(s * (x + dx), s * y))
            p.drawLine(QPointF(s * x, s * y), QPointF(s * x, s * (y + dy)))
    elif kind == "spark":
        for angle in range(0, 360, 45):
            r = s * (0.36 if angle % 90 == 0 else 0.27)
            a = math.radians(angle)
            p.drawLine(
                QPointF(s / 2, s / 2),
                QPointF(s / 2 + math.cos(a) * r, s / 2 + math.sin(a) * r),
            )
        p.drawEllipse(QPointF(s / 2, s / 2), s * 0.07, s * 0.07)
    elif kind == "road":
        path = QPainterPath()
        path.moveTo(s * 0.18, s * 0.72)
        path.lineTo(s * 0.36, s * 0.38)
        path.lineTo(s * 0.52, s * 0.58)
        path.lineTo(s * 0.80, s * 0.26)
        p.drawPath(path)
    elif kind == "river":
        path = QPainterPath()
        path.moveTo(s * 0.18, s * 0.68)
        path.cubicTo(s * 0.34, s * 0.20, s * 0.56, s * 0.90, s * 0.82, s * 0.32)
        p.drawPath(path)
    elif kind == "eraser":
        p.save()
        p.translate(s / 2, s / 2)
        p.rotate(-35)
        p.drawRoundedRect(QRectF(-s * 0.25, -s * 0.16, s * 0.50, s * 0.32), 3, 3)
        p.drawLine(QPointF(0, -s * 0.16), QPointF(0, s * 0.16))
        p.restore()
    p.end()
    return QIcon(pm)


def make_app_icon(size: int = 64) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    cx = cy = size / 2
    r = size * 0.45
    p.setBrush(QColor("#12221f"))
    p.setPen(QPen(QColor("#d8b45a"), max(1.5, size * 0.035)))
    p.drawPolygon(
        QPolygonF(
            [
                QPointF(cx + math.cos(math.radians(a)) * r, cy + math.sin(math.radians(a)) * r)
                for a in (-90, -30, 30, 90, 150, 210)
            ]
        )
    )
    pen = QPen(QColor("#e7c66d"), max(1.4, size * 0.045), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    s = size
    crown = QPainterPath()
    crown.moveTo(s * 0.30, s * 0.58)
    crown.lineTo(s * 0.30, s * 0.40)
    crown.lineTo(s * 0.41, s * 0.49)
    crown.lineTo(s * 0.50, s * 0.32)
    crown.lineTo(s * 0.59, s * 0.49)
    crown.lineTo(s * 0.70, s * 0.40)
    crown.lineTo(s * 0.70, s * 0.58)
    crown.closeSubpath()
    p.drawPath(crown)
    p.end()
    return QIcon(pm)


class LogoWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(44, 48)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy, r = self.width() / 2, self.height() / 2, 19.0
        pts = [
            QPointF(cx + math.cos(math.radians(a)) * r, cy + math.sin(math.radians(a)) * r)
            for a in (-90, -30, 30, 90, 150, 210)
        ]
        poly = QPolygonF(pts)
        p.setBrush(QColor("#152a26"))
        p.setPen(QPen(QColor("#d8b45a"), 1.6))
        p.drawPolygon(poly)
        # 简化的王冠。
        p.setPen(QPen(QColor("#e7c66d"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        crown = QPainterPath()
        crown.moveTo(cx - 9, cy + 5)
        crown.lineTo(cx - 9, cy - 5)
        crown.lineTo(cx - 4.5, cy)
        crown.lineTo(cx, cy - 8)
        crown.lineTo(cx + 4.5, cy)
        crown.lineTo(cx + 9, cy - 5)
        crown.lineTo(cx + 9, cy + 5)
        crown.closeSubpath()
        p.drawPath(crown)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#d8b45a"))
        p.drawEllipse(QPointF(cx, cy + 9), 1.6, 1.6)
        p.end()


class Minimap(QWidget):
    navigate = pyqtSignal(float, float)

    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self.model = model
        self.image: QImage | None = None
        self.world_rect: QRectF = QRectF(0, 0, 1, 1)
        self.view_rect: QRectF = QRectF()
        self.setMinimumHeight(205)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pressing = False
        self._image_rect = QRectF()

    def set_model(self, model) -> None:
        self.model = model
        self.image = None
        self.update()

    def set_image(self, image: QImage | None) -> None:
        self.image = image
        self.update()

    def set_view_rect(self, world: QRectF) -> None:
        self.view_rect = QRectF(world)
        self.update()

    def _compute_rects(self) -> None:
        bx, by, bw, bh = world_bounds(self.model.width, self.model.height)
        self.world_rect = QRectF(bx, by, bw, bh)
        margin = 9
        avail = QRectF(
            margin,
            margin,
            max(1, self.width() - margin * 2),
            max(1, self.height() - margin * 2),
        )
        ratio = bw / bh
        w = avail.width()
        h = w / ratio
        if h > avail.height():
            h = avail.height()
            w = h * ratio
        self._image_rect = QRectF(
            avail.left() + (avail.width() - w) / 2,
            avail.top() + (avail.height() - h) / 2,
            w,
            h,
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._compute_rects()
        outer = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(QColor(255, 255, 255, 24), 1))
        p.setBrush(QColor("#0a1117"))
        p.drawRoundedRect(outer, 10, 10)
        if self.image is None and self.model is not None:
            self.image = self.model.to_minimap_image()
        if self.image is not None:
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(self._image_rect.adjusted(1, 1, -1, -1), 4, 4)
            p.setClipPath(clip)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(self._image_rect, self.image)
            # 视野框。
            if not self.view_rect.isNull() and not self.world_rect.isNull():
                sx = self._image_rect.left() + (
                    (self.view_rect.left() - self.world_rect.left()) / self.world_rect.width()
                ) * self._image_rect.width()
                sy = self._image_rect.top() + (
                    (self.view_rect.top() - self.world_rect.top()) / self.world_rect.height()
                ) * self._image_rect.height()
                sw = self.view_rect.width() / self.world_rect.width() * self._image_rect.width()
                sh = self.view_rect.height() / self.world_rect.height() * self._image_rect.height()
                view = QRectF(sx, sy, sw, sh).intersected(self._image_rect)
                p.setBrush(QColor(255, 255, 255, 16))
                p.setPen(QPen(QColor("#f0d894"), 1.5))
                p.drawRect(view)
            p.restore()
        p.end()

    def _navigate(self, pos) -> None:
        if self._image_rect.isEmpty():
            return
        x = (pos.x() - self._image_rect.left()) / self._image_rect.width()
        y = (pos.y() - self._image_rect.top()) / self._image_rect.height()
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
        wx = self.world_rect.left() + x * self.world_rect.width()
        wy = self.world_rect.top() + y * self.world_rect.height()
        self.navigate.emit(wx, wy)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressing = True
            self._navigate(event.position())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pressing:
            self._navigate(event.position())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._pressing = False


class StatCard(QWidget):
    def __init__(self, title: str, accent: str, parent=None) -> None:
        super().__init__(parent)
        self.title = title
        self.accent = QColor(accent)
        self.value = "—"
        self.sub = ""
        self.setFixedHeight(66)

    def set_value(self, value: str, sub: str = "") -> None:
        self.value = value
        self.sub = sub
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.setBrush(QColor("#18232c"))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 8, 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.accent)
        p.drawRoundedRect(QRectF(10, 12, 3, self.height() - 24), 1.5, 1.5)
        f = QFont(self.font())
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor("#8fa1aa"))
        p.drawText(QRectF(21, 8, self.width() - 28, 16), Qt.AlignmentFlag.AlignLeft, self.title)
        f.setPixelSize(19)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#eee7d7"))
        p.drawText(
            QRectF(21, 24, self.width() - 28, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.value,
        )
        f.setPixelSize(9)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor("#738791"))
        p.drawText(
            QRectF(21, 47, self.width() - 28, 12),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.sub,
        )
        p.end()


class Toast(QWidget):
    """自动消失的轻量提示条。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text = ""
        self._timer = None
        self.hide()

    def show_message(self, text: str, duration: int = 2400) -> None:
        from PyQt6.QtCore import QTimer

        self._text = text
        self.adjustSize()
        self.resize(max(220, self.fontMetrics().horizontalAdvance(text) + 52), 40)
        if self.parent() is not None:
            pw = self.parent().width()
            ph = self.parent().height()
            self.move((pw - self.width()) // 2, ph - 74)
        self.show()
        self.raise_()
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.hide)
        self._timer.start(duration)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(216, 180, 90, 100), 1))
        p.setBrush(QColor(16, 27, 34, 242))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 12, 12)
        p.setPen(QColor("#efe8d7"))
        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()
