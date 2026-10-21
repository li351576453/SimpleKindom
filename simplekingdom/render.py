"""地图渲染：低倍率使用整图缓存，高倍率逐格绘制。"""

from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

from .constants import (
    CACHE_HEX_SIZE,
    OVERLAY_RIVER,
    OVERLAY_ROAD,
    TERRAIN_COLORS,
    TERRAIN_DARK_COLORS,
    TERRAIN_LIGHT_COLORS,
    Terrain,
)
from .hexmath import (
    CORNER_ANGLES,
    EDGE_FOR_DIR,
    NEIGHBORS_EVEN,
    NEIGHBORS_ODD,
    SQRT3,
    world_bounds,
)
from .model import MapModel

PAD_WORLD = 2.0
DYNAMIC_THRESHOLD = 6.2


def _qcolor(value: str, alpha: int = 255) -> QColor:
    color = QColor(value)
    color.setAlpha(alpha)
    return color


class TerrainRenderer:
    """负责地形底图缓存和地图绘制。"""

    def __init__(self, model: MapModel) -> None:
        self.model = model
        self.base_image: QImage | None = None
        self.cache_size = CACHE_HEX_SIZE
        self.image_world_rect = QRectF()
        self._corner_offsets = [
            (math.cos(math.radians(a)), math.sin(math.radians(a))) for a in CORNER_ANGLES
        ]
        self._colors = {int(t): QColor(TERRAIN_COLORS[t]) for t in Terrain}
        self._dark_colors = {int(t): QColor(TERRAIN_DARK_COLORS[t]) for t in Terrain}
        self._light_colors = {int(t): QColor(TERRAIN_LIGHT_COLORS[t]) for t in Terrain}
        self._variants: dict[tuple[int, int], list[QColor]] = {}
        for t in Terrain:
            base = QColor(TERRAIN_COLORS[t])
            variants = [base]
            for factor in (1.045, 0.955, 1.085, 0.905):
                c = QColor(base)
                if factor >= 1.0:
                    c = c.lighter(int(factor * 100) - 100 + 100)
                else:
                    c = c.darker(int((2.0 - factor) * 100))
                variants.append(c)
            self._variants[int(t)] = variants

    # ------------------------------------------------------------------ 缓存
    def rebuild_base(self) -> None:
        model = self.model
        size = self.cache_size
        bx, by, bw, bh = world_bounds(model.width, model.height)
        rect = QRectF(bx - PAD_WORLD, by - PAD_WORLD, bw + PAD_WORLD * 2, bh + PAD_WORLD * 2)
        self.image_world_rect = rect
        iw = max(1, int(math.ceil(rect.width() * size)))
        ih = max(1, int(math.ceil(rect.height() * size)))
        image = QImage(iw, ih, QImage.Format.Format_RGB32)
        image.fill(QColor(TERRAIN_COLORS[Terrain.OCEAN]))
        counts = np.bincount(np.frombuffer(model.terrain, dtype=np.uint8), minlength=7)
        if counts.max(initial=0) >= model.cell_count:
            # 初始全海洋时直接铺底色，避免绘制 25 万个相同六边形。
            dominant = int(np.argmax(counts))
            image.fill(self._colors[dominant])
            self.base_image = image
            return
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        corners = [(dx * size, dy * size) for dx, dy in self._corner_offsets]
        terrain = model.terrain
        width = model.width
        ox = -rect.left() * size
        oy = -rect.top() * size
        for row in range(model.height):
            cy = 1.5 * size * row + oy
            xoff = 0.5 * (row & 1)
            for col in range(width):
                idx = row * width + col
                cx = SQRT3 * size * (col + xoff) + ox
                poly = QPolygonF(
                    [
                        QPointF(cx + corners[0][0], cy + corners[0][1]),
                        QPointF(cx + corners[1][0], cy + corners[1][1]),
                        QPointF(cx + corners[2][0], cy + corners[2][1]),
                        QPointF(cx + corners[3][0], cy + corners[3][1]),
                        QPointF(cx + corners[4][0], cy + corners[4][1]),
                        QPointF(cx + corners[5][0], cy + corners[5][1]),
                    ]
                )
                painter.setBrush(self._colors[terrain[idx]])
                painter.drawPolygon(poly)
        painter.end()
        self.base_image = image

    def refresh_cells(self, indices: list[int]) -> None:
        if self.base_image is None:
            return
        model = self.model
        size = self.cache_size
        rect = self.image_world_rect
        ox = -rect.left() * size
        oy = -rect.top() * size
        painter = QPainter(self.base_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        corners = [(dx * size, dy * size) for dx, dy in self._corner_offsets]
        for idx in indices:
            row, col = divmod(idx, model.width)
            terrain = model.terrain[idx]
            cx = SQRT3 * size * (col + 0.5 * (row & 1)) + ox
            cy = 1.5 * size * row + oy
            poly = QPolygonF(
                [
                    QPointF(cx + corners[0][0], cy + corners[0][1]),
                    QPointF(cx + corners[1][0], cy + corners[1][1]),
                    QPointF(cx + corners[2][0], cy + corners[2][1]),
                    QPointF(cx + corners[3][0], cy + corners[3][1]),
                    QPointF(cx + corners[4][0], cy + corners[4][1]),
                    QPointF(cx + corners[5][0], cy + corners[5][1]),
                ]
            )
            painter.setBrush(self._colors[terrain])
            painter.drawPolygon(poly)
        painter.end()

    # ------------------------------------------------------------------ 绘制
    def paint(
        self,
        painter: QPainter,
        hex_size: float,
        offset: QPointF,
        viewport: QRectF,
        *,
        force_dynamic: bool = False,
    ) -> None:
        if self.base_image is None:
            self.rebuild_base()
        if hex_size >= DYNAMIC_THRESHOLD or force_dynamic:
            self._paint_dynamic(painter, hex_size, offset, viewport)
        else:
            self._paint_cached(painter, hex_size, offset, viewport)

    def _paint_cached(
        self,
        painter: QPainter,
        hex_size: float,
        offset: QPointF,
        viewport: QRectF,
    ) -> None:
        assert self.base_image is not None
        rect = self.image_world_rect
        target = QRectF(
            offset.x() + rect.left() * hex_size,
            offset.y() + rect.top() * hex_size,
            rect.width() * hex_size,
            rect.height() * hex_size,
        )
        visible = target.intersected(viewport)
        if visible.isEmpty():
            return
        source = QRectF(
            (visible.left() - target.left()) / target.width() * self.base_image.width(),
            (visible.top() - target.top()) / target.height() * self.base_image.height(),
            visible.width() / target.width() * self.base_image.width(),
            visible.height() / target.height() * self.base_image.height(),
        )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, hex_size < 5.0)
        painter.drawImage(visible, self.base_image, source)

    def _paint_dynamic(
        self,
        painter: QPainter,
        hex_size: float,
        offset: QPointF,
        viewport: QRectF,
    ) -> None:
        model = self.model
        width, height = model.width, model.height
        # 根据屏幕坐标反推可见行列范围。
        row_min = max(0, int((viewport.top() - offset.y()) / (1.5 * hex_size)) - 2)
        row_max = min(
            height - 1,
            int((viewport.bottom() - offset.y()) / (1.5 * hex_size)) + 2,
        )
        col_min = max(0, int((viewport.left() - offset.x()) / (SQRT3 * hex_size)) - 2)
        col_max = min(
            width - 1,
            int((viewport.right() - offset.x()) / (SQRT3 * hex_size)) + 2,
        )
        if row_min > row_max or col_min > col_max:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        corners = self._corner_offsets
        terrain = model.terrain
        grid_pen = QPen(QColor(8, 18, 24, 72), 1.0)
        coast_pen = QPen(QColor(15, 41, 55, 180), max(1.0, hex_size * 0.06))
        water_types = (Terrain.OCEAN, Terrain.LAKE)
        for row in range(row_min, row_max + 1):
            cy = offset.y() + 1.5 * hex_size * row
            xoff = 0.5 * (row & 1)
            for col in range(col_min, col_max + 1):
                idx = row * width + col
                cx = offset.x() + SQRT3 * hex_size * (col + xoff)
                points = [
                    QPointF(cx + dx * hex_size, cy + dy * hex_size) for dx, dy in corners
                ]
                poly = QPolygonF(points)
                brush = self._colors[terrain[idx]]
                painter.setBrush(brush)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPolygon(poly)
                # 同色地块用极淡的内高光，避免高倍率下完全平板。
                if (col * 31 + row * 17) % 7 == 0:
                    highlight = QColor(255, 255, 255, 10)
                    painter.setBrush(highlight)
                    painter.drawPolygon(poly)
                painter.setPen(grid_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolygon(poly)
                # 陆水交界线。
                if terrain[idx] not in water_types:
                    table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
                    for direction, (dc, dr) in enumerate(table):
                        nc, nr = col + dc, row + dr
                        if 0 <= nc < width and 0 <= nr < height:
                            if terrain[nr * width + nc] in water_types:
                                e = EDGE_FOR_DIR[direction]
                                painter.setPen(coast_pen)
                                painter.drawLine(points[e], points[(e + 1) % 6])
                                painter.setPen(grid_pen)


class OverlayRenderer:
    """道路与河流以六边形边链描线的方式绘制。"""

    @staticmethod
    def paint(
        painter: QPainter,
        model: MapModel,
        hex_size: float,
        offset: QPointF,
        viewport: QRectF,
    ) -> None:
        width = model.width
        height = model.height
        row_min = max(0, int((viewport.top() - offset.y()) / (1.5 * hex_size)) - 2)
        row_max = min(height - 1, int((viewport.bottom() - offset.y()) / (1.5 * hex_size)) + 2)
        col_min = max(0, int((viewport.left() - offset.x()) / (SQRT3 * hex_size)) - 2)
        col_max = min(width - 1, int((viewport.right() - offset.x()) / (SQRT3 * hex_size)) + 2)
        if row_min > row_max or col_min > col_max:
            return

        road_path = QPainterPath()
        river_path = QPainterPath()
        has_roads = False
        has_rivers = False
        overlay = model.overlay
        road_edges = model.road_edges
        river_edges = model.river_edges
        corner_offsets = [
            (math.cos(math.radians(a)), math.sin(math.radians(a))) for a in CORNER_ANGLES
        ]

        for row in range(row_min, row_max + 1):
            cy = offset.y() + 1.5 * hex_size * row
            xoff = 0.5 * (row & 1)
            base = row * width
            for col in range(col_min, col_max + 1):
                idx = base + col
                ov = overlay[idx]
                if not ov:
                    continue
                cx = offset.x() + SQRT3 * hex_size * (col + xoff)
                screen_corners = [
                    QPointF(cx + dx * hex_size, cy + dy * hex_size)
                    for dx, dy in corner_offsets
                ]
                if ov & OVERLAY_ROAD:
                    mask = road_edges[idx]
                    if mask:
                        has_roads = True
                        for edge in range(6):
                            if mask & (1 << edge):
                                road_path.moveTo(screen_corners[edge])
                                road_path.lineTo(screen_corners[(edge + 1) % 6])
                if ov & OVERLAY_RIVER:
                    mask = river_edges[idx]
                    if mask:
                        has_rivers = True
                        for edge in range(6):
                            if mask & (1 << edge):
                                river_path.moveTo(screen_corners[edge])
                                river_path.lineTo(screen_corners[(edge + 1) % 6])
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if has_rivers:
            casing = QPen(QColor("#4a96b8"), max(0.65, hex_size * 0.23))
            casing.setCapStyle(Qt.PenCapStyle.RoundCap)
            casing.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(casing)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(river_path)
            core = QPen(
                QColor(TERRAIN_COLORS[Terrain.LAKE]),
                max(0.35, hex_size * 0.12),
            )
            core.setCapStyle(Qt.PenCapStyle.RoundCap)
            core.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(core)
            painter.drawPath(river_path)
        if has_roads:
            # 深棕色外缘压边，主体使用亮棕色，避免和深绿色地形混在一起。
            edge = QPen(QColor(78, 47, 24, 220), max(0.75, hex_size * 0.20))
            edge.setCapStyle(Qt.PenCapStyle.RoundCap)
            edge.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(edge)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(road_path)
            road = QPen(QColor("#c08048"), max(0.40, hex_size * 0.12))
            road.setCapStyle(Qt.PenCapStyle.RoundCap)
            road.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(road)
            painter.drawPath(road_path)


def render_overview(model: MapModel, target_width: int = 2400) -> QImage:
    """导出整张地图的 PNG 图像（不含编辑器网格和悬停笔刷）。"""
    bx, by, bw, bh = world_bounds(model.width, model.height)
    hex_size = max(0.8, (target_width - 80) / max(1.0, bw))
    out_w = int(math.ceil(bw * hex_size + 80))
    out_h = int(math.ceil(bh * hex_size + 80))
    image = QImage(out_w, out_h, QImage.Format.Format_ARGB32)
    image.fill(QColor("#12202c"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    offset = QPointF(40 - bx * hex_size, 40 - by * hex_size)

    renderer = TerrainRenderer(model)
    renderer.rebuild_base()
    if renderer.base_image is not None:
        ir = renderer.image_world_rect
        dest = QRectF(
            offset.x() + ir.left() * hex_size,
            offset.y() + ir.top() * hex_size,
            ir.width() * hex_size,
            ir.height() * hex_size,
        )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(dest, renderer.base_image)
    OverlayRenderer.paint(painter, model, hex_size, offset, QRectF(0, 0, out_w, out_h))
    painter.end()
    return image
