"""地图编辑画布：绘制、缩放、平移与笔刷交互。"""

from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPolygonF,
    QUndoStack,
)
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget

from .commands import CellStrokeCommand
from .constants import (
    OVERLAY_NAMES,
    OVERLAY_RIVER,
    OVERLAY_ROAD,
    TERRAIN_COLORS,
    TERRAIN_NAMES,
    TOOL_ERASER,
    TOOL_RIVER,
    TOOL_ROAD,
    TOOL_TERRAIN,
    Terrain,
)
from .edgegeom import (
    edge_endpoints_world,
    edge_geometry_key,
    key_to_point,
    nearest_edge_of_cell,
    nearest_vertex_of_cell,
    vertex_path,
)
from .hexmath import (
    CORNER_ANGLES,
    hex_center,
    hex_line,
    hexes_in_radius,
    screen_to_hex,
    world_bounds,
)
from .model import CellChange, MapModel
from .render import OverlayRenderer, TerrainRenderer


class ZoomPanel(QFrame):
    zoom_in = pyqtSignal()
    zoom_out = pyqtSignal()
    fit = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ZoomPanel")
        self.setFixedHeight(34)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(2)
        self.out_btn = QToolButton(self)
        self.out_btn.setText("−")
        self.out_btn.setToolTip("缩小 (Ctrl+-)")
        self.out_btn.clicked.connect(self.zoom_out)
        self.percent = QLabel("100%", self)
        self.percent.setObjectName("ZoomPercent")
        self.percent.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.percent.setMinimumWidth(52)
        self.in_btn = QToolButton(self)
        self.in_btn.setText("+")
        self.in_btn.setToolTip("放大 (Ctrl++)")
        self.in_btn.clicked.connect(self.zoom_in)
        self.fit_btn = QToolButton(self)
        self.fit_btn.setText("⤢")
        self.fit_btn.setToolTip("适应窗口 (Ctrl+0)")
        self.fit_btn.clicked.connect(self.fit)
        for b in (self.out_btn, self.in_btn, self.fit_btn):
            b.setObjectName("ZoomButton")
            b.setFixedSize(26, 26)
            layout.addWidget(b)
        layout.insertWidget(1, self.percent)

    def set_percent(self, value: int) -> None:
        self.percent.setText(f"{value}%")


class MapCanvas(QWidget):
    cursor_info = pyqtSignal(str)
    view_changed = pyqtSignal(QRectF)
    zoom_changed = pyqtSignal(int)
    map_edited = pyqtSignal(bool)
    path_changed = pyqtSignal(int)

    def __init__(self, model: MapModel, undo_stack: QUndoStack, parent=None) -> None:
        super().__init__(parent)
        self.model = model
        self.undo_stack = undo_stack
        self.renderer = TerrainRenderer(model)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.hex_size = 2.0
        self.offset = QPointF(0, 0)
        self._fit_scale = 2.0
        self._min_scale = 0.5
        self._max_scale = 76.0
        self._initial_fit_done = False

        self.tool = TOOL_TERRAIN
        self.selected_terrain = Terrain.PLAINS
        self.brush_size = 1
        self._hover_cell: tuple[int, int] | None = None
        self._hover_world = QPointF()
        self._space_down = False
        self._panning = False
        self._pan_origin = QPointF()
        self._pan_offset_origin = QPointF()
        self._painting = False
        self._erase_mode = False
        self._last_paint_screen = QPointF()
        self._last_paint_cell: tuple[int, int] | None = None
        self._stroke: dict[int, list[int]] = {}
        self._stroke_overlay_changed = False
        self._stroke_terrain_cells: set[int] = set()
        self._stroke_preview_cells: list[int] = []
        self._hover_edge: tuple[int, int] | None = None
        self._edge_painting = False
        self._edge_erase = False
        self._edge_layer = "river"
        self._edge_specs: list[tuple[int, int]] = []
        self._edge_seen: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        self._edge_last_pos = QPointF()
        self._stroke_touched_cells: set[int] = set()
        self._river_groups_before: tuple[tuple[tuple[int, int], ...], ...] | None = None
        self._road_groups_before: tuple[tuple[tuple[int, int], ...], ...] | None = None
        self.path_mode = False
        self._path_points: list[tuple[int, int]] = []
        self._path_edges: list[tuple[int, int]] = []
        self._path_hover: tuple[tuple[int, int], tuple[float, float]] | None = None
        self._path_layer = "river"
        self._path_groups_before: tuple[tuple[tuple[int, int], ...], ...] | None = None
        self._path_road_groups_before: (
            tuple[tuple[tuple[int, int], ...], ...] | None
        ) = None
        self._has_land = self._compute_has_land()

        self.zoom_panel = ZoomPanel(self)
        self.zoom_panel.zoom_in.connect(lambda: self._zoom_at(1.25, self.rect().center()))
        self.zoom_panel.zoom_out.connect(lambda: self._zoom_at(1 / 1.25, self.rect().center()))
        self.zoom_panel.fit.connect(self.fit_to_view)
        self.zoom_panel.raise_()

    # ------------------------------------------------------------------ 状态
    def _compute_has_land(self) -> bool:
        return bool(np.any(np.frombuffer(self.model.terrain, dtype=np.uint8) != 0))

    def set_model(self, model: MapModel) -> None:
        self.model = model
        self.renderer = TerrainRenderer(model)
        self.renderer.rebuild_base()
        self._has_land = self._compute_has_land()
        self._hover_cell = None
        self._hover_edge = None
        self._edge_painting = False
        self._edge_specs.clear()
        self._edge_seen.clear()
        self._stroke_touched_cells.clear()
        self._river_groups_before = None
        self._road_groups_before = None
        self._clear_path()
        self._stroke.clear()
        self.fit_to_view()
        self.update()

    def set_tool(self, tool: str, terrain: Terrain | None = None) -> None:
        previous_tool = self.tool
        self.tool = tool
        if terrain is not None:
            self.selected_terrain = terrain
        if tool not in (TOOL_ROAD, TOOL_RIVER):
            self._hover_edge = None
        if tool != previous_tool:
            self._clear_path()
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if tool == TOOL_ERASER
            else Qt.CursorShape.CrossCursor
        )
        self.update()

    def set_path_mode(self, enabled: bool) -> None:
        """河流工具是否使用路径点连线模式。"""
        self.path_mode = bool(enabled)
        if not self.path_mode:
            self._clear_path()
        self._path_hover = None
        self.update()

    def path_point_count(self) -> int:
        return len(self._path_points)

    def _set_path_hover(self, pos: QPointF) -> None:
        if not self.path_mode or self.tool not in (TOOL_ROAD, TOOL_RIVER):
            self._path_hover = None
            return
        cell = self._screen_to_cell(pos)
        if cell is None:
            self._path_hover = None
            return
        world_x = (pos.x() - self.offset.x()) / self.hex_size
        world_y = (pos.y() - self.offset.y()) / self.hex_size
        self._path_hover = nearest_vertex_of_cell(
            self.model.index(*cell), world_x, world_y, self.model.width
        )

    def _recompute_path(self) -> bool:
        if len(self._path_points) < 2:
            self._path_edges = []
            return True
        combined: list[tuple[int, int]] = []
        width, height = self.model.width, self.model.height
        for start, end in zip(self._path_points, self._path_points[1:]):
            if start == end:
                continue
            edges = vertex_path(start, end, width, height)
            if edges is None:
                return False
            combined.extend(edges)
        deduped: list[tuple[int, int]] = []
        for spec in combined:
            if deduped and edge_geometry_key(
                deduped[-1][0], deduped[-1][1], self.model.width
            ) == edge_geometry_key(spec[0], spec[1], self.model.width):
                continue
            deduped.append(spec)
        self._path_edges = deduped
        return True

    def _path_add_point(self, pos: QPointF) -> None:
        cell = self._screen_to_cell(pos)
        if cell is None:
            return
        world_x = (pos.x() - self.offset.x()) / self.hex_size
        world_y = (pos.y() - self.offset.y()) / self.hex_size
        key, _point = nearest_vertex_of_cell(
            self.model.index(*cell), world_x, world_y, self.model.width
        )
        if self._path_points and self._path_points[-1] == key:
            return
        if not self._path_points:
            self._path_layer = (
                "road" if self.tool == TOOL_ROAD else "river"
            )
        self._path_points.append(key)
        if self._path_groups_before is None:
            self._path_groups_before = self.model.copy_river_groups()
            self._path_road_groups_before = self.model.copy_road_groups()
        if not self._recompute_path():
            self._path_points.pop()
            if not self._path_points:
                self._path_groups_before = None
                self._path_road_groups_before = None
            self._recompute_path()
        self.path_changed.emit(len(self._path_points))
        self.update()

    def _path_remove_last(self) -> None:
        if not self._path_points:
            return
        self._path_points.pop()
        if not self._path_points:
            self._path_groups_before = None
            self._path_road_groups_before = None
        self._recompute_path()
        self.path_changed.emit(len(self._path_points))
        self.update()

    def _clear_path(self) -> None:
        if not self._path_points and not self._path_edges:
            self._path_groups_before = None
            self._path_road_groups_before = None
            self._path_hover = None
            return
        self._path_points.clear()
        self._path_edges.clear()
        self._path_groups_before = None
        self._path_road_groups_before = None
        self._path_hover = None
        self.path_changed.emit(0)
        self.update()

    def _path_commit(self) -> None:
        if len(self._path_points) < 2 or not self._path_edges:
            return
        river_before = self._path_groups_before
        road_before = self._path_road_groups_before
        specs = list(self._path_edges)
        if river_before is None:
            river_before = self.model.copy_river_groups()
        if road_before is None:
            road_before = self.model.copy_road_groups()
        if self._path_layer == "road":
            self.model.add_road_edge_group(specs)
            label = "路径点绘制道路"
        else:
            self.model.add_river_edge_group(specs)
            label = "路径点绘制河流"
        river_after = self.model.copy_river_groups()
        road_after = self.model.copy_road_groups()
        if river_after != river_before or road_after != road_before:
            self.model.rebuild_all_edges()
            self.model.touch()
            command = CellStrokeCommand(
                self.model,
                [],
                self._command_callback,
                label,
                already_applied=True,
                before_river_groups=river_before,
                after_river_groups=river_after,
                before_road_groups=road_before,
                after_road_groups=road_after,
            )
            self.undo_stack.push(command)
        self._path_points.clear()
        self._path_edges.clear()
        self._path_groups_before = None
        self._path_road_groups_before = None
        self._path_hover = None
        self.path_changed.emit(0)
        self.update()

    def _draw_path_preview(self, painter: QPainter) -> None:
        line_color = (
            QColor("#f5e7bd")
            if self._path_layer == "road"
            else QColor("#8bd8ef")
        )
        if self._path_edges:
            pen = QPen(line_color, max(2.0, self.hex_size * 0.16))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for owner, edge in self._path_edges:
                a, b = edge_endpoints_world(owner, edge, self.model.width)
                painter.drawLine(
                    QPointF(
                        self.offset.x() + a[0] * self.hex_size,
                        self.offset.y() + a[1] * self.hex_size,
                    ),
                    QPointF(
                        self.offset.x() + b[0] * self.hex_size,
                        self.offset.y() + b[1] * self.hex_size,
                    ),
                )

        marker_pen = QPen(
            QColor("#fff2cf") if self._path_layer == "road" else QColor("#dff7ff"),
            max(1.0, self.hex_size * 0.08),
        )
        painter.setPen(marker_pen)
        painter.setBrush(
            QColor("#b58b3a") if self._path_layer == "road" else QColor("#2c7fa3")
        )
        radius = max(2.5, self.hex_size * 0.18)
        for key in self._path_points:
            x, y = key_to_point(key)
            painter.drawEllipse(
                QPointF(
                    self.offset.x() + x * self.hex_size,
                    self.offset.y() + y * self.hex_size,
                ),
                radius,
                radius,
            )

        if self._path_hover is not None:
            key, _point = self._path_hover
            x, y = key_to_point(key)
            hover_pos = QPointF(
                self.offset.x() + x * self.hex_size,
                self.offset.y() + y * self.hex_size,
            )
            if self._path_points:
                last_x, last_y = key_to_point(self._path_points[-1])
                last_pos = QPointF(
                    self.offset.x() + last_x * self.hex_size,
                    self.offset.y() + last_y * self.hex_size,
                )
                dash = QPen(line_color, 1.0, Qt.PenStyle.DashLine)
                painter.setPen(dash)
                painter.drawLine(last_pos, hover_pos)
            painter.setPen(QPen(QColor("#f5e7bd"), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(hover_pos, radius + 2.0, radius + 2.0)

    def set_brush_size(self, size: int) -> None:
        self.brush_size = max(1, min(12, int(size)))
        self.update()

    def refresh_full(self) -> None:
        self.renderer.rebuild_base()
        self._has_land = self._compute_has_land()
        self.update()

    def zoom_percent(self) -> int:
        if self._fit_scale <= 0:
            return 100
        return int(round(self.hex_size / self._fit_scale * 100))

    # ------------------------------------------------------------------ 视图
    def _emit_view(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        world = QRectF(
            (0 - self.offset.x()) / self.hex_size,
            (0 - self.offset.y()) / self.hex_size,
            self.width() / self.hex_size,
            self.height() / self.hex_size,
        )
        self.view_changed.emit(world)
        self.zoom_changed.emit(self.zoom_percent())
        self.zoom_panel.set_percent(self.zoom_percent())

    def fit_to_view(self) -> None:
        bx, by, bw, bh = world_bounds(self.model.width, self.model.height)
        margin = 48
        avail_w = max(100, self.width() - margin * 2)
        avail_h = max(100, self.height() - margin * 2)
        scale = min(avail_w / bw, avail_h / bh)
        self._fit_scale = scale
        self._min_scale = scale * 0.70
        self._max_scale = 76.0
        self.hex_size = scale
        self.offset = QPointF(
            (self.width() - bw * scale) / 2 - bx * scale,
            (self.height() - bh * scale) / 2 - by * scale,
        )
        self._initial_fit_done = True
        self._emit_view()
        self.update()

    def center_on_cell(self, col: float, row: float) -> None:
        cx, cy = hex_center(col, row, 1.0)
        self.center_on_world(cx, cy)

    def center_on_world(self, x: float, y: float) -> None:
        self.offset = QPointF(
            self.width() / 2 - x * self.hex_size,
            self.height() / 2 - y * self.hex_size,
        )
        self._emit_view()
        self.update()

    def _zoom_at(self, factor: float, anchor: QPoint) -> None:
        new_scale = max(self._min_scale, min(self._max_scale, self.hex_size * factor))
        if abs(new_scale - self.hex_size) < 1e-9:
            return
        world_x = (anchor.x() - self.offset.x()) / self.hex_size
        world_y = (anchor.y() - self.offset.y()) / self.hex_size
        self.hex_size = new_scale
        self.offset = QPointF(
            anchor.x() - world_x * new_scale,
            anchor.y() - world_y * new_scale,
        )
        self._emit_view()
        self.update()

    def zoom_in(self) -> None:
        self._zoom_at(1.25, self.rect().center())

    def zoom_out(self) -> None:
        self._zoom_at(1 / 1.25, self.rect().center())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._initial_fit_done:
            self.fit_to_view()
        else:
            self._emit_view()
        self.zoom_panel.adjustSize()
        self.zoom_panel.move(
            self.width() - self.zoom_panel.width() - 18,
            self.height() - self.zoom_panel.height() - 16,
        )
        self.zoom_panel.raise_()

    # ------------------------------------------------------------------ 坐标
    def _screen_to_cell(self, pos: QPointF) -> tuple[int, int] | None:
        return screen_to_hex(
            pos.x() - self.offset.x(),
            pos.y() - self.offset.y(),
            self.hex_size,
            self.model.width,
            self.model.height,
        )

    def _cell_world(self, col: int, row: int) -> tuple[float, float]:
        return hex_center(col, row, 1.0)

    def _brush_cells(self, col: int, row: int):
        radius = self.brush_size - 1
        for cc, rr, _ring in hexes_in_radius(col, row, radius):
            if 0 <= cc < self.model.width and 0 <= rr < self.model.height:
                yield cc, rr

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg = QLinearGradient(0, 0, self.width(), self.height())
        bg.setColorAt(0.0, QColor("#0c151d"))
        bg.setColorAt(1.0, QColor("#081017"))
        painter.fillRect(self.rect(), bg)

        bx, by, bw, bh = world_bounds(self.model.width, self.model.height)
        map_rect = QRectF(
            self.offset.x() + bx * self.hex_size,
            self.offset.y() + by * self.hex_size,
            bw * self.hex_size,
            bh * self.hex_size,
        )
        # 地图下方的柔和阴影。
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawRoundedRect(map_rect.translated(0, 8).adjusted(-4, -4, 4, 4), 10, 10)

        viewport = QRectF(0, 0, self.width(), self.height())
        painter.save()
        painter.setClipRect(viewport)
        self.renderer.paint(painter, self.hex_size, self.offset, viewport)
        OverlayRenderer.paint(painter, self.model, self.hex_size, self.offset, viewport)

        if self.path_mode and self.tool in (TOOL_ROAD, TOOL_RIVER):
            self._draw_path_preview(painter)
        elif self.tool in (TOOL_ROAD, TOOL_RIVER):
            self._draw_edge_preview(painter)
        elif self._painting and self._stroke_preview_cells:
            self._draw_stroke_preview(painter)
        if self._hover_cell and not self._panning and self.tool not in (TOOL_ROAD, TOOL_RIVER):
            self._draw_brush_preview(painter)
        if not self._has_land:
            self._draw_empty_hint(painter)
        painter.restore()

        # 地图外框。
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(214, 186, 124, 42), 1.0))
        painter.drawRoundedRect(map_rect, 8, 8)
        painter.end()

    def _draw_brush_preview(self, painter: QPainter) -> None:
        col, row = self._hover_cell
        color = QColor(TERRAIN_COLORS[self.selected_terrain])
        if self.tool == TOOL_ROAD:
            color = QColor("#f5e7bd")
        elif self.tool == TOOL_RIVER:
            color = QColor("#8bd8ef")
        elif self.tool == TOOL_ERASER:
            color = QColor("#ff9a84")
        fill = QColor(color)
        fill.setAlpha(52)
        outline = QColor(color)
        outline.setAlpha(210)
        pen = QPen(outline, 1.4)
        painter.setPen(pen)
        painter.setBrush(fill)
        for cc, rr in self._brush_cells(col, row):
            cx, cy = self._cell_world(cc, rr)
            sx = self.offset.x() + cx * self.hex_size
            sy = self.offset.y() + cy * self.hex_size
            poly = QPolygonF(
                [
                    QPointF(
                        sx + math.cos(math.radians(a)) * self.hex_size,
                        sy + math.sin(math.radians(a)) * self.hex_size,
                    )
                    for a in CORNER_ANGLES
                ]
            )
            painter.drawPolygon(poly)
        # 圆心细点。
        sx = self.offset.x() + hex_center(col, row)[0] * self.hex_size
        sy = self.offset.y() + hex_center(col, row)[1] * self.hex_size
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(outline)
        painter.drawEllipse(QPointF(sx, sy), 2.2, 2.2)

    def _edge_screen_endpoints(
        self,
        cell: int,
        edge: int,
    ) -> tuple[QPointF, QPointF]:
        a, b = edge_endpoints_world(cell, edge, self.model.width)
        return (
            QPointF(
                self.offset.x() + a[0] * self.hex_size,
                self.offset.y() + a[1] * self.hex_size,
            ),
            QPointF(
                self.offset.x() + b[0] * self.hex_size,
                self.offset.y() + b[1] * self.hex_size,
            ),
        )

    def _draw_edge_preview(self, painter: QPainter) -> None:
        width = max(2.6, self.hex_size * 0.16)
        if self._edge_specs:
            if self._edge_erase:
                color = QColor("#ff9a84")
            elif self._edge_layer == "road":
                color = QColor("#f5e7bd")
            else:
                color = QColor("#8bd8ef")
            pen = QPen(color, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            for cell, edge in self._edge_specs[-240:]:
                a, b = self._edge_screen_endpoints(cell, edge)
                painter.drawLine(a, b)
        if self._hover_edge is not None and not self._panning:
            cell, edge = self._hover_edge
            a, b = self._edge_screen_endpoints(cell, edge)
            pen = QPen(QColor("#f0d894"), max(width + 1.6, 3.2))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(a, b)

    def _draw_stroke_preview(self, painter: QPainter) -> None:
        color = QColor("#f5e7bd")
        fill = QColor(color)
        fill.setAlpha(58)
        painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 120), 1.0))
        painter.setBrush(fill)
        for idx in self._stroke_preview_cells[-160:]:
            row, col = divmod(idx, self.model.width)
            cx, cy = self._cell_world(col, row)
            sx = self.offset.x() + cx * self.hex_size
            sy = self.offset.y() + cy * self.hex_size
            poly = QPolygonF(
                [
                    QPointF(
                        sx + math.cos(math.radians(a)) * self.hex_size,
                        sy + math.sin(math.radians(a)) * self.hex_size,
                    )
                    for a in CORNER_ANGLES
                ]
            )
            painter.drawPolygon(poly)

    def _draw_empty_hint(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() / 2, self.height() / 2
        panel = QRectF(cx - 240, cy - 68, 480, 136)
        painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.setBrush(QColor(8, 18, 26, 150))
        painter.drawRoundedRect(panel, 16, 16)
        font = QFont(self.font())
        font.setPixelSize(21)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#e9e2cf"))
        painter.drawText(
            panel.adjusted(0, 22, 0, -58),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "一片尚未命名的海",
        )
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor("#9fb1bb"))
        painter.drawText(
            panel.adjusted(20, 66, -20, -18),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "从左侧挑选地块开始绘制，或在右侧随机生成一片大陆。",
        )

    # ------------------------------------------------------------------ 鼠标
    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.setFocus()
        pos = event.position()
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_down
        ):
            self._panning = True
            self._pan_origin = pos
            self._pan_offset_origin = QPointF(self.offset)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            if (
                self.path_mode
                and self.tool in (TOOL_ROAD, TOOL_RIVER)
            ):
                if self._path_points:
                    self._path_remove_last()
                    event.accept()
                    return
                self._begin_edge_stroke(pos, erase=True)
                event.accept()
                return
            if self.tool in (TOOL_ROAD, TOOL_RIVER):
                self._begin_edge_stroke(pos, erase=True)
                event.accept()
                return
            cell = self._screen_to_cell(pos)
            if cell:
                self._begin_stroke(cell, erase_overlay=True)
                self._last_paint_screen = pos
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if (
                self.path_mode
                and self.tool in (TOOL_ROAD, TOOL_RIVER)
            ):
                self._path_add_point(pos)
                event.accept()
                return
            if self.tool in (TOOL_ROAD, TOOL_RIVER):
                self._begin_edge_stroke(pos, erase=False)
                event.accept()
                return
            cell = self._screen_to_cell(pos)
            if cell:
                self._begin_stroke(cell, erase_overlay=False)
                self._last_paint_screen = pos
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if self._panning:
            delta = pos - self._pan_origin
            self.offset = self._pan_offset_origin + delta
            self._emit_view()
            self.update()
            return
        if self.path_mode and self.tool in (TOOL_ROAD, TOOL_RIVER):
            self._set_path_hover(pos)
            self.update()
            super().mouseMoveEvent(event)
            return
        if self.tool in (TOOL_ROAD, TOOL_RIVER):
            self._update_edge_hover(pos)
            if self._edge_painting:
                self._continue_edge_stroke(pos)
            super().mouseMoveEvent(event)
            return
        cell = self._screen_to_cell(pos)
        if cell != self._hover_cell:
            self._hover_cell = cell
            if cell:
                self._update_cursor_info(cell)
            self.update()
        if self._painting:
            self._continue_stroke(pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning and event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.LeftButton,
        ):
            self._panning = False
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        if self._edge_painting and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
        ):
            self._continue_edge_stroke(event.position())
            self._finish_edge_stroke()
            return
        if self._painting and event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
        ):
            self._continue_stroke(event.position())
            self._finish_stroke()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.angleDelta().y() == 0:
            return
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        self._zoom_at(factor, event.position().toPoint())
        event.accept()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_cell = None
        self._hover_edge = None
        self._path_hover = None
        self.update()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.path_mode
            and self.tool in (TOOL_ROAD, TOOL_RIVER)
        ):
            self._path_commit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if self.path_mode and self.tool in (TOOL_ROAD, TOOL_RIVER):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._path_commit()
                return
            if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
                self._path_remove_last()
                return
            if event.key() == Qt.Key.Key_Escape:
                self._clear_path()
                return
        if event.key() == Qt.Key.Key_Escape:
            if self._edge_painting:
                self._cancel_edge_stroke()
                return
            if self._painting:
                self._cancel_stroke()
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            if not self._panning:
                self.setCursor(Qt.CursorShape.CrossCursor)
            return
        super().keyReleaseEvent(event)

    def _update_cursor_info(self, cell: tuple[int, int]) -> None:
        col, row = cell
        terrain = self.model.terrain_at(col, row)
        overlay = self.model.overlay_at(col, row)
        extras = []
        if overlay & OVERLAY_ROAD:
            extras.append(OVERLAY_NAMES[OVERLAY_ROAD])
        if overlay & OVERLAY_RIVER:
            extras.append(OVERLAY_NAMES[OVERLAY_RIVER])
        suffix = f" · {'/'.join(extras)}" if extras else ""
        if self.tool in (TOOL_ROAD, TOOL_RIVER) and self._hover_edge is not None:
            suffix += " · 道路边" if self.tool == TOOL_ROAD else " · 河流边"
        self.cursor_info.emit(f"({col}, {row})  {TERRAIN_NAMES[terrain]}{suffix}")

    def _edge_at(self, pos: QPointF) -> tuple[int, int] | None:
        cell = self._screen_to_cell(pos)
        if cell is None:
            return None
        world_x = (pos.x() - self.offset.x()) / self.hex_size
        world_y = (pos.y() - self.offset.y()) / self.hex_size
        edge, distance = nearest_edge_of_cell(
            self.model.index(*cell), world_x, world_y, self.model.width
        )
        if self.hex_size >= 6.0 and distance > 0.62:
            return None
        return self.model.index(*cell), edge

    def _update_edge_hover(self, pos: QPointF) -> None:
        edge = self._edge_at(pos)
        if edge == self._hover_edge:
            return
        self._hover_edge = edge
        if edge is not None:
            cell, _edge = edge
            self._hover_cell = self.model.colrow(cell)
            self._update_cursor_info(self._hover_cell)
        self.update()

    def _begin_edge_stroke(self, pos: QPointF, *, erase: bool) -> None:
        self._edge_painting = True
        self._edge_erase = erase
        self._edge_layer = "road" if self.tool == TOOL_ROAD else "river"
        self._edge_specs.clear()
        self._edge_seen.clear()
        self._edge_last_pos = pos
        self._river_groups_before = self.model.copy_river_groups()
        self._road_groups_before = self.model.copy_road_groups()
        self._add_edge_at(pos)
        self.update()

    def _add_edge_at(self, pos: QPointF) -> None:
        edge = self._edge_at(pos)
        if edge is None:
            return
        cell, edge_index = edge
        key = edge_geometry_key(cell, edge_index, self.model.width)
        if key in self._edge_seen:
            return
        self._edge_seen.add(key)
        self._edge_specs.append((cell, edge_index))
        self._hover_edge = (cell, edge_index)
        self._hover_cell = self.model.colrow(cell)
        self.update()

    def _continue_edge_stroke(self, pos: QPointF) -> None:
        start = self._edge_last_pos
        distance = math.hypot(pos.x() - start.x(), pos.y() - start.y())
        steps = max(1, int(distance / max(1.0, self.hex_size * 0.22)))
        for step in range(1, steps + 1):
            t = step / steps
            self._add_edge_at(
                QPointF(
                    start.x() + (pos.x() - start.x()) * t,
                    start.y() + (pos.y() - start.y()) * t,
                )
            )
        self._edge_last_pos = pos
        self.update()

    def _finish_edge_stroke(self) -> None:
        self._edge_painting = False
        specs = list(self._edge_specs)
        river_before = self._river_groups_before
        road_before = self._road_groups_before
        if specs:
            if self._edge_layer == "road":
                if self._edge_erase:
                    self.model.remove_road_edges(specs)
                    label = "擦除道路边"
                else:
                    self.model.add_road_edge_group(specs)
                    label = "绘制道路边"
            else:
                if self._edge_erase:
                    self.model.remove_river_edges(specs)
                    label = "擦除河流边"
                else:
                    self.model.add_river_edge_group(specs)
                    label = "绘制河流边"
            river_after = self.model.copy_river_groups()
            road_after = self.model.copy_road_groups()
            river_changed = river_before is not None and river_after != river_before
            road_changed = road_before is not None and road_after != road_before
            if river_changed or road_changed:
                self.model.rebuild_all_edges()
                self.model.touch()
                command = CellStrokeCommand(
                    self.model,
                    [],
                    self._command_callback,
                    label,
                    already_applied=True,
                    before_river_groups=river_before,
                    after_river_groups=river_after,
                    before_road_groups=road_before,
                    after_road_groups=road_after,
                )
                self.undo_stack.push(command)
        self._edge_specs.clear()
        self._edge_seen.clear()
        self._river_groups_before = None
        self._road_groups_before = None
        self.update()

    def _cancel_edge_stroke(self) -> None:
        self._edge_painting = False
        self._edge_specs.clear()
        self._edge_seen.clear()
        self._river_groups_before = None
        self._road_groups_before = None
        self.update()

    # ------------------------------------------------------------------ 涂抹
    def _begin_stroke(self, cell: tuple[int, int], *, erase_overlay: bool) -> None:
        self._painting = True
        self._erase_mode = erase_overlay
        self._stroke.clear()
        self._stroke_overlay_changed = False
        self._stroke_terrain_cells.clear()
        self._stroke_preview_cells.clear()
        self._stroke_touched_cells.clear()
        self._river_groups_before = (
            self.model.copy_river_groups() if self.tool == TOOL_ERASER else None
        )
        self._road_groups_before = (
            self.model.copy_road_groups() if self.tool == TOOL_ERASER else None
        )
        self._last_paint_screen = QPointF()
        self._last_paint_cell = cell
        self._apply_brush(cell)
        self.update()

    def _continue_stroke(self, pos: QPointF) -> None:
        target = self._screen_to_cell(pos)
        if target is None:
            return
        if self._last_paint_cell is None:
            self._last_paint_cell = target
            self._apply_brush(target)
            return
        if target == self._last_paint_cell:
            return
        for cell in hex_line(self._last_paint_cell, target)[1:]:
            self._apply_brush(cell)
        self._last_paint_cell = target
        self._last_paint_screen = pos
        self.update()

    def _apply_brush(self, cell: tuple[int, int]) -> None:
        col, row = cell
        changed_any = False
        for cc, rr in self._brush_cells(col, row):
            idx = rr * self.model.width + cc
            if self.tool == TOOL_ERASER:
                self._stroke_touched_cells.add(idx)
            old_t = self.model.terrain[idx]
            old_o = self.model.overlay[idx]
            new_t = old_t
            new_o = old_o
            if self._erase_mode:
                new_o = old_o & OVERLAY_RIVER
            elif self.tool == TOOL_TERRAIN:
                new_t = int(self.selected_terrain)
            elif self.tool == TOOL_ERASER:
                new_t = int(Terrain.OCEAN)
                new_o = old_o & OVERLAY_RIVER
            elif self.tool == TOOL_ROAD:
                new_o = old_o | OVERLAY_ROAD
            if new_t == old_t and new_o == old_o:
                if idx not in self._stroke_preview_cells and self.tool == TOOL_ROAD:
                    self._stroke_preview_cells.append(idx)
                continue
            if idx not in self._stroke:
                self._stroke[idx] = [old_t, int(new_t), old_o, int(new_o)]
            else:
                self._stroke[idx][1] = int(new_t)
                self._stroke[idx][3] = int(new_o)
            self.model.terrain[idx] = int(new_t)
            self.model.overlay[idx] = int(new_o)
            if new_t != old_t:
                self._stroke_terrain_cells.add(idx)
            if new_o != old_o:
                self._stroke_overlay_changed = True
            if self.tool == TOOL_ROAD:
                self._stroke_preview_cells.append(idx)
            changed_any = True
        if self._stroke_terrain_cells:
            self.renderer.refresh_cells(list(self._stroke_terrain_cells))
            self._stroke_terrain_cells.clear()
        if changed_any:
            self._update_cursor_info((col, row))

    def _finish_stroke(self) -> None:
        self._painting = False
        changes = [
            CellChange(index, vals[0], vals[1], vals[2], vals[3])
            for index, vals in self._stroke.items()
            if vals[0] != vals[1] or vals[2] != vals[3]
        ]
        river_before = self._river_groups_before
        road_before = self._road_groups_before
        river_changed = False
        road_changed = False
        if self.tool == TOOL_ERASER and self._stroke_touched_cells:
            specs = [
                (index, edge)
                for index in self._stroke_touched_cells
                for edge in range(6)
            ]
            river_changed = self.model.remove_river_edges(specs)
            road_changed = self.model.remove_road_edges(specs)
        river_after = self.model.copy_river_groups() if river_before is not None else None
        road_after = self.model.copy_road_groups() if road_before is not None else None
        river_changed = river_changed or (
            river_before is not None and river_after != river_before
        )
        road_changed = road_changed or (
            road_before is not None and road_after != road_before
        )

        if self._stroke_overlay_changed or river_changed or road_changed:
            self.model.rebuild_all_edges()
        if changes or river_changed or road_changed:
            self.model.touch()
            label = {
                TOOL_ERASER: "擦除地块与路径",
                TOOL_TERRAIN: f"绘制{TERRAIN_NAMES[self.selected_terrain]}",
            }.get(self.tool, "绘制")
            if self._erase_mode:
                label = "擦除路径"
            command = CellStrokeCommand(
                self.model,
                changes,
                self._command_callback,
                label,
                already_applied=True,
                before_river_groups=river_before,
                after_river_groups=river_after,
                before_road_groups=road_before,
                after_road_groups=road_after,
            )
            self.undo_stack.push(command)
            if any(c.old_terrain != c.new_terrain for c in changes):
                self._has_land = self._compute_has_land()
        self._stroke.clear()
        self._stroke_preview_cells.clear()
        self._stroke_touched_cells.clear()
        self._river_groups_before = None
        self._road_groups_before = None
        self.update()

    def _cancel_stroke(self) -> None:
        self._painting = False
        for idx, vals in self._stroke.items():
            self.model.terrain[idx] = vals[0]
            self.model.overlay[idx] = vals[2]
        self.model.rebuild_all_edges()
        self._stroke.clear()
        self._stroke_preview_cells.clear()
        self._stroke_touched_cells.clear()
        self._river_groups_before = None
        self._road_groups_before = None
        self.renderer.rebuild_base()
        self._has_land = self._compute_has_land()
        self.update()

    def _command_callback(self, command, full: bool) -> None:
        if full:
            self.renderer.rebuild_base()
            self._has_land = self._compute_has_land()
        else:
            cells = getattr(command, "cells", [])
            if cells:
                terrain_changed = any(
                    c.old_terrain != c.new_terrain for c in getattr(command, "changes", [])
                )
                if terrain_changed:
                    self.renderer.refresh_cells(cells)
                self._has_land = self._compute_has_land() if terrain_changed else self._has_land
        self.update()
        self.map_edited.emit(bool(full))
