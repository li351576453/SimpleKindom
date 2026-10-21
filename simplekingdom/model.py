"""地图模型：地块、覆盖层、道路/河流边链缓存。"""

from __future__ import annotations

import math
import random
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np

from .constants import (
    DEFAULT_MAP_SIZE,
    OVERLAY_ALL,
    OVERLAY_RIVER,
    OVERLAY_ROAD,
    TERRAIN_COLORS,
    Terrain,
)
from .edgegeom import (
    adjacent_edge_choices,
    cell_center_world,
    cell_path_bank_specs,
    edge_geometry_key,
    edge_midpoint_world,
    edge_vertex_keys,
)
from .hexmath import (
    NEIGHBORS_EVEN,
    NEIGHBORS_ODD,
)


@dataclass
class MapSnapshot:
    terrain: bytes
    overlay: bytes
    river_groups: tuple[tuple[tuple[int, int], ...], ...] = ()
    road_groups: tuple[tuple[tuple[int, int], ...], ...] = ()


@dataclass
class CellChange:
    index: int
    old_terrain: int
    new_terrain: int
    old_overlay: int
    new_overlay: int


@dataclass
class MapStats:
    terrain_counts: dict[int, int] = field(default_factory=dict)
    road_cells: int = 0
    river_cells: int = 0


@dataclass
class CurvatureCircle:
    """离散中心线三个相邻格点确定的曲率圆。"""

    center_x: float
    center_y: float
    radius: float
    anchor: int


@dataclass
class RiverCurvatureInfo:
    """一条独立河流边链的曲率圆记录。"""

    edges: tuple[tuple[int, int], ...]
    centerline: tuple[tuple[float, float], ...]
    circles: tuple[CurvatureCircle, ...]
    selected: CurvatureCircle | None


class MapModel:
    """500×500 六边形地图数据。

    terrain / overlay 使用 bytearray，索引为 row * width + col。
    道路与河流保存在同一覆盖层的不同二进制位中，边归属由独立边链重建。
    """

    def __init__(self, width: int = DEFAULT_MAP_SIZE, height: int = DEFAULT_MAP_SIZE) -> None:
        self.width = width
        self.height = height
        self.terrain = bytearray(width * height)
        self.overlay = bytearray(width * height)
        self.road_edges = bytearray(width * height)
        self.river_edges = bytearray(width * height)
        self.river_groups: list[set[tuple[int, int]]] = []
        self.road_groups: list[set[tuple[int, int]]] = []
        self.river_curvatures: list[RiverCurvatureInfo] = []
        self._river_edge_mode = False
        self._road_edge_mode = False
        self.seed: int = random.SystemRandom().randrange(1, 2_000_000_000)
        self.name: str = "未命名大陆"
        self.file_path: str | None = None
        self.revision: int = 0
        self.terrain_color_lut = np.array(
            [tuple(int(TERRAIN_COLORS[t].lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)) for t in Terrain],
            dtype=np.uint8,
        )

    # ------------------------------------------------------------------ 基础
    @property
    def cell_count(self) -> int:
        return self.width * self.height

    def index(self, col: int, row: int) -> int:
        return row * self.width + col

    def colrow(self, index: int) -> tuple[int, int]:
        return index % self.width, index // self.width

    def in_bounds(self, col: int, row: int) -> bool:
        return 0 <= col < self.width and 0 <= row < self.height

    def terrain_at(self, col: int, row: int) -> Terrain:
        return Terrain(self.terrain[row * self.width + col])

    def overlay_at(self, col: int, row: int) -> int:
        return self.overlay[row * self.width + col]

    def clear(self) -> None:
        self.terrain[:] = bytes(self.cell_count)
        self.overlay[:] = bytes(self.cell_count)
        self.road_edges[:] = bytes(self.cell_count)
        self.river_edges[:] = bytes(self.cell_count)
        self.river_groups.clear()
        self.road_groups.clear()
        self.river_curvatures.clear()
        self._river_edge_mode = False
        self._road_edge_mode = False
        self.touch()

    def fill(self, terrain: Terrain) -> None:
        self.terrain[:] = bytes([int(terrain)]) * self.cell_count
        self.overlay[:] = bytes(self.cell_count)
        self.road_edges[:] = bytes(self.cell_count)
        self.river_edges[:] = bytes(self.cell_count)
        self.river_groups.clear()
        self.road_groups.clear()
        self.river_curvatures.clear()
        self._river_edge_mode = False
        self._road_edge_mode = False
        self.touch()

    def touch(self) -> None:
        self.revision += 1

    def snapshot(self) -> MapSnapshot:
        river_groups = tuple(tuple(sorted(group)) for group in self.river_groups)
        road_groups = tuple(tuple(sorted(group)) for group in self.road_groups)
        return MapSnapshot(
            bytes(self.terrain), bytes(self.overlay), river_groups, road_groups
        )

    def restore(self, snapshot: MapSnapshot) -> None:
        self.terrain[:] = snapshot.terrain
        self.overlay[:] = snapshot.overlay
        self.river_groups = [set(group) for group in snapshot.river_groups]
        self.road_groups = [set(group) for group in snapshot.road_groups]
        self._river_edge_mode = True
        self._road_edge_mode = True
        self.rebuild_all_edges()
        self.touch()

    def set_arrays(
        self,
        terrain: bytes,
        overlay: bytes,
        river_groups: Iterable[Iterable[tuple[int, int]]] | None = None,
        road_groups: Iterable[Iterable[tuple[int, int]]] | None = None,
    ) -> None:
        if len(terrain) != self.cell_count or len(overlay) != self.cell_count:
            raise ValueError("地图数组尺寸不匹配")
        self.terrain[:] = terrain
        self.overlay[:] = overlay
        self.river_groups = (
            [set(group) for group in river_groups] if river_groups is not None else []
        )
        self.road_groups = (
            [set(group) for group in road_groups] if road_groups is not None else []
        )
        self._river_edge_mode = river_groups is not None
        self._road_edge_mode = road_groups is not None
        self.rebuild_all_edges()
        self.touch()

    def copy_river_groups(self) -> tuple[tuple[tuple[int, int], ...], ...]:
        return tuple(tuple(sorted(group)) for group in self.river_groups)

    def copy_road_groups(self) -> tuple[tuple[tuple[int, int], ...], ...]:
        return tuple(tuple(sorted(group)) for group in self.road_groups)

    def set_river_groups(self, groups: Iterable[Iterable[tuple[int, int]]]) -> None:
        self.river_groups = [set(group) for group in groups]
        self._river_edge_mode = True

    def set_road_groups(self, groups: Iterable[Iterable[tuple[int, int]]]) -> None:
        self.road_groups = [set(group) for group in groups]
        self._road_edge_mode = True

    # ------------------------------------------------------------------ 修改
    def set_terrain(self, index: int, terrain: Terrain) -> None:
        self.terrain[index] = int(terrain)

    def set_overlay(self, index: int, overlay: int) -> None:
        self.overlay[index] = overlay & OVERLAY_ALL

    def apply_cells(
        self,
        updates: list[tuple[int, int | None, int | None]],
        *,
        rebuild_edges: bool = True,
        touch: bool = True,
    ) -> None:
        """批量修改。每项为 (index, terrain_or_None, overlay_or_None)。"""
        edge_dirty = False
        for index, terrain, overlay in updates:
            if terrain is not None and self.terrain[index] != terrain:
                self.terrain[index] = int(terrain)
            if overlay is not None:
                value = overlay & OVERLAY_ALL
                if self.overlay[index] != value:
                    self.overlay[index] = value
                    edge_dirty = True
        if rebuild_edges and edge_dirty:
            self.rebuild_all_edges()
        if touch:
            self.touch()

    # ------------------------------------------------------------------ 描边
    def rebuild_all_edges(self) -> None:
        self.road_edges[:] = bytes(self.cell_count)
        self.river_edges[:] = bytes(self.cell_count)
        self._rebuild_road_edge_chains()
        self._rebuild_river_edge_chains()

    # ------------------------------------------------------------------ 河流 / 道路边链
    def add_river_edge_group(self, specs: Iterable[tuple[int, int]]) -> bool:
        """把一组按绘制顺序排列的六边形边追加为独立河道。"""
        changed = self._add_edge_group(self.river_groups, specs)
        if changed:
            self._river_edge_mode = True
        return changed

    def add_road_edge_group(self, specs: Iterable[tuple[int, int]]) -> bool:
        """把一组按绘制顺序排列的六边形边追加为独立道路。"""
        changed = self._add_edge_group(self.road_groups, specs)
        if changed:
            self._road_edge_mode = True
        return changed

    def _add_edge_group(
        self,
        groups: list[set[tuple[int, int]]],
        specs: Iterable[tuple[int, int]],
    ) -> bool:
        """追加独立边链；边最终归属于曲率圆心一侧。"""
        width, height = self.width, self.height
        clean: list[tuple[int, int]] = []
        seen_geometry: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        for raw_cell, raw_edge in specs:
            cell, edge = int(raw_cell), int(raw_edge)
            if not (0 <= cell < self.cell_count and 0 <= edge < 6):
                continue
            key = edge_geometry_key(cell, edge, width)
            if key in seen_geometry:
                continue
            seen_geometry.add(key)
            clean.append((cell, edge))
        if not clean:
            return False

        for existing in groups:
            if seen_geometry <= self._group_geometry_keys(existing):
                return False

        points = [edge_midpoint_world(cell, edge, width) for cell, edge in clean]
        circles = self._circles_along_points(points)
        selected = max(circles, key=lambda c: c.radius) if circles else None

        group: set[tuple[int, int]] = set()
        for cell, edge in clean:
            choices = adjacent_edge_choices(cell, edge, width, height)
            if selected is None:
                group.add((cell, edge))
                continue
            chosen = min(
                choices,
                key=lambda item: (
                    (cell_center_world(item[0], width)[0] - selected.center_x) ** 2
                    + (cell_center_world(item[0], width)[1] - selected.center_y) ** 2
                ),
            )
            group.add(chosen)
        groups.append(group)
        return True

    def remove_river_edges(self, specs: Iterable[tuple[int, int]]) -> bool:
        """从所有独立河道中删除指定几何边。"""
        changed = self._remove_edges_from_groups(self.river_groups, specs)
        if changed:
            self._river_edge_mode = True
        return changed

    def remove_road_edges(self, specs: Iterable[tuple[int, int]]) -> bool:
        """从所有独立道路中删除指定几何边。"""
        changed = self._remove_edges_from_groups(self.road_groups, specs)
        if changed:
            self._road_edge_mode = True
        return changed

    def _remove_edges_from_groups(
        self,
        groups: list[set[tuple[int, int]]],
        specs: Iterable[tuple[int, int]],
    ) -> bool:
        width = self.width
        removed: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        for raw_cell, raw_edge in specs:
            cell, edge = int(raw_cell), int(raw_edge)
            if 0 <= cell < self.cell_count and 0 <= edge < 6:
                removed.add(edge_geometry_key(cell, edge, width))
        if not removed:
            return False
        changed = False
        new_groups: list[set[tuple[int, int]]] = []
        for group in groups:
            filtered = {
                item
                for item in group
                if edge_geometry_key(item[0], item[1], width) not in removed
            }
            if len(filtered) != len(group):
                changed = True
            if filtered:
                new_groups.append(filtered)
        if changed:
            groups[:] = new_groups
        return changed

    def _group_geometry_keys(
        self,
        group: Iterable[tuple[int, int]],
    ) -> set[tuple[tuple[int, int], tuple[int, int]]]:
        return {
            edge_geometry_key(owner, edge, self.width)
            for owner, edge in group
            if 0 <= owner < self.cell_count and 0 <= edge < 6
        }

    def _circles_along_points(
        self,
        points: list[tuple[float, float]],
    ) -> list[CurvatureCircle]:
        circles: list[CurvatureCircle] = []
        for index in range(1, len(points) - 1):
            circle = self._circumcircle(
                points[index - 1], points[index], points[index + 1], index
            )
            if circle is not None:
                circles.append(circle)
        return circles

    def _ordered_group_edges(
        self,
        group: set[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        """把无序边集合按共享端点整理成一条较长的连续边链。"""
        edges = sorted(group)
        if not edges:
            return []
        vertex_edges: dict[tuple[int, int], list[int]] = {}
        edge_vertices: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {}
        for index, (owner, edge) in enumerate(edges):
            a, b = edge_vertex_keys(owner, edge, self.width)
            edge_vertices[index] = (a, b)
            vertex_edges.setdefault(a, []).append(index)
            vertex_edges.setdefault(b, []).append(index)
        endpoints = sorted(
            vertex for vertex, incident in vertex_edges.items() if len(incident) == 1
        )
        start_vertex = endpoints[0] if endpoints else min(vertex_edges)
        path: list[tuple[int, int]] = []
        used: set[int] = set()
        current = start_vertex
        guard = 0
        while guard < len(edges) + 2:
            guard += 1
            candidates = [
                index for index in vertex_edges.get(current, ()) if index not in used
            ]
            if not candidates:
                break
            index = candidates[0]
            used.add(index)
            path.append(edges[index])
            a, b = edge_vertices[index]
            current = b if current == a else a
        return path

    def _convert_legacy_road_overlay(self) -> None:
        """旧版格子道路迁移：每条连通道路取一条外岸转成边链。"""
        arr = np.frombuffer(self.overlay, dtype=np.uint8)
        indices = {int(i) for i in np.flatnonzero(arr & OVERLAY_ROAD)}
        self._road_edge_mode = True
        if not indices:
            return
        for component in self._river_components(indices):
            specs = cell_path_bank_specs(
                sorted(component),
                self.width,
                self.height,
                upper=True,
            )
            if specs:
                self.add_road_edge_group(specs)

    def _rebuild_road_edge_chains(self) -> None:
        """由独立道路边链分组重建道路边掩码。"""
        self.road_edges[:] = bytes(self.cell_count)
        if not self.road_groups and not self._road_edge_mode:
            self._convert_legacy_road_overlay()

        arr = np.frombuffer(self.overlay, dtype=np.uint8)
        for raw_index in np.flatnonzero(arr & OVERLAY_ROAD):
            index = int(raw_index)
            self.overlay[index] &= 0xFF ^ OVERLAY_ROAD

        valid_groups: list[set[tuple[int, int]]] = []
        for group in self.road_groups:
            valid = {
                (int(owner), int(edge))
                for owner, edge in group
                if 0 <= int(owner) < self.cell_count and 0 <= int(edge) < 6
            }
            if valid:
                valid_groups.append(valid)
        valid_groups.sort(key=min)
        self.road_groups = valid_groups

        seen_geometry: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        for group in self.road_groups:
            for owner, edge in group:
                key = edge_geometry_key(owner, edge, self.width)
                if key in seen_geometry:
                    continue
                seen_geometry.add(key)
                self.road_edges[owner] |= 1 << edge
                self.overlay[owner] |= OVERLAY_ROAD

    def _convert_legacy_river_overlay(self) -> None:
        """旧版格子河流迁移：每条连通河流取一条外岸转成边链。"""
        arr = np.frombuffer(self.overlay, dtype=np.uint8)
        indices = {int(i) for i in np.flatnonzero(arr & OVERLAY_RIVER)}
        self._river_edge_mode = True
        if not indices:
            return
        for component in self._river_components(indices):
            specs = cell_path_bank_specs(
                sorted(component),
                self.width,
                self.height,
                upper=True,
            )
            if specs:
                self.add_river_edge_group(specs)

    def _rebuild_river_edge_chains(self) -> None:
        """由独立边链分组重建渲染边掩码和曲率圆记录。"""
        self.river_edges[:] = bytes(self.cell_count)
        if not self.river_groups and not self._river_edge_mode:
            self._convert_legacy_river_overlay()

        # 清除旧的河流格标记；只保留道路位，随后按边归属重新标记。
        arr = np.frombuffer(self.overlay, dtype=np.uint8)
        for raw_index in np.flatnonzero(arr & OVERLAY_RIVER):
            index = int(raw_index)
            self.overlay[index] &= 0xFF ^ OVERLAY_RIVER

        valid_groups: list[set[tuple[int, int]]] = []
        for group in self.river_groups:
            valid = {
                (int(owner), int(edge))
                for owner, edge in group
                if 0 <= int(owner) < self.cell_count and 0 <= int(edge) < 6
            }
            if valid:
                valid_groups.append(valid)
        valid_groups.sort(key=min)
        self.river_groups = valid_groups

        self.river_curvatures.clear()
        seen_geometry: set[tuple[tuple[int, int], tuple[int, int]]] = set()
        for group_index, group in enumerate(self.river_groups):
            ordered = self._ordered_group_edges(group)
            points = [
                edge_midpoint_world(owner, edge, self.width) for owner, edge in ordered
            ]
            circles = self._circles_along_points(points)
            selected = max(circles, key=lambda c: c.radius) if circles else None

            # 曲率圆心确定后，重新把每条边归到更接近圆心的六边形。
            if selected is not None:
                normalized: set[tuple[int, int]] = set()
                for hint_cell, hint_edge in group:
                    choices = adjacent_edge_choices(
                        hint_cell, hint_edge, self.width, self.height
                    )
                    chosen = min(
                        choices,
                        key=lambda item: (
                            (cell_center_world(item[0], self.width)[0] - selected.center_x) ** 2
                            + (cell_center_world(item[0], self.width)[1] - selected.center_y) ** 2
                        ),
                    )
                    normalized.add(chosen)
                group = normalized
                self.river_groups[group_index] = group

            self.river_curvatures.append(
                RiverCurvatureInfo(
                    edges=tuple(sorted(group)),
                    centerline=tuple(points),
                    circles=tuple(circles),
                    selected=selected,
                )
            )
            for owner, edge in group:
                key = edge_geometry_key(owner, edge, self.width)
                if key in seen_geometry:
                    continue
                seen_geometry.add(key)
                self.river_edges[owner] |= 1 << edge
                self.overlay[owner] |= OVERLAY_RIVER

    def _river_components(self, river_indices: set[int]) -> list[list[int]]:
        """把覆盖层格子拆成六邻接连通块。"""
        visited: set[int] = set()
        components: list[list[int]] = []
        for start in sorted(river_indices):
            if start in visited:
                continue
            visited.add(start)
            queue = deque([start])
            component: list[int] = []
            while queue:
                current = queue.popleft()
                component.append(current)
                row, col = divmod(current, self.width)
                table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
                for dc, dr in table:
                    nc, nr = col + dc, row + dr
                    if not (0 <= nc < self.width and 0 <= nr < self.height):
                        continue
                    nxt = nr * self.width + nc
                    if nxt in river_indices and nxt not in visited:
                        visited.add(nxt)
                        queue.append(nxt)
            components.append(component)
        return components

    @staticmethod
    def _circumcircle(
        p1: tuple[float, float],
        p2: tuple[float, float],
        p3: tuple[float, float],
        anchor: int,
    ) -> CurvatureCircle | None:
        """三个格心的外接圆；共线时返回 None。"""
        ax, ay = p1
        bx, by = p2
        cx, cy = p3
        d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) < 1e-12:
            return None
        a2 = ax * ax + ay * ay
        b2 = bx * bx + by * by
        c2 = cx * cx + cy * cy
        ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
        uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
        radius = math.hypot(ux - bx, uy - by)
        if not math.isfinite(radius) or not math.isfinite(ux) or not math.isfinite(uy):
            return None
        return CurvatureCircle(ux, uy, radius, anchor)

    # ------------------------------------------------------------------ 统计
    def stats(self) -> MapStats:
        counts = np.bincount(np.frombuffer(self.terrain, dtype=np.uint8), minlength=7)
        arr = np.frombuffer(self.overlay, dtype=np.uint8)
        return MapStats(
            terrain_counts={int(i): int(v) for i, v in enumerate(counts)},
            road_cells=int(np.count_nonzero(arr & OVERLAY_ROAD)),
            river_cells=int(np.count_nonzero(arr & OVERLAY_RIVER)),
        )

    def land_count(self) -> int:
        counts = np.bincount(np.frombuffer(self.terrain, dtype=np.uint8), minlength=7)
        return int(counts.sum() - counts[Terrain.OCEAN])

    def count_terrain_components(self, terrain: Terrain) -> int:
        mask = np.frombuffer(self.terrain, dtype=np.uint8) == int(terrain)
        return self._count_components(mask)

    def count_overlay_components(self, flag: int) -> int:
        mask = (np.frombuffer(self.overlay, dtype=np.uint8) & flag) != 0
        return self._count_components(mask)

    def _count_components(self, mask: np.ndarray) -> int:
        if not mask.any():
            return 0
        visited = np.zeros(self.cell_count, dtype=bool)
        width = self.width
        count = 0
        for raw in np.flatnonzero(mask):
            idx = int(raw)
            if visited[idx]:
                continue
            count += 1
            visited[idx] = True
            stack = [idx]
            while stack:
                cur = stack.pop()
                row, col = divmod(cur, width)
                table = (NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN)
                for dc, dr in table:
                    nc, nr = col + dc, row + dr
                    if not (0 <= nc < width and 0 <= nr < self.height):
                        continue
                    nidx = nr * width + nc
                    if mask[nidx] and not visited[nidx]:
                        visited[nidx] = True
                        stack.append(nidx)
        return count

    # ------------------------------------------------------------------ 小地图
    def to_minimap_image(self):
        """返回 width×height 的 RGB 小地图图像（overlay 会叠加在上面）。"""
        from PyQt6.QtGui import QImage

        terrain = np.frombuffer(self.terrain, dtype=np.uint8)
        overlay = np.frombuffer(self.overlay, dtype=np.uint8)
        rgb = self.terrain_color_lut[terrain].copy()
        # 道路为亮棕色，河流为浅蓝色，和主视图一致。
        rgb[(overlay & OVERLAY_ROAD) != 0] = (192, 128, 72)
        rgb[(overlay & OVERLAY_RIVER) != 0] = (121, 201, 230)
        image = QImage(rgb.data, self.width, self.height, self.width * 3, QImage.Format.Format_RGB888)
        return image.copy()

    # ------------------------------------------------------------------ 序列化
    def metadata(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "seed": self.seed,
            "name": self.name,
        }

    def apply_metadata(self, data: dict) -> None:
        self.seed = int(data.get("seed", self.seed))
        self.name = str(data.get("name", self.name))[:80]
