"""随机地图生成器。

生成目标
--------
* 一块完整的主大陆，外海散布小岛；
* 平原可大面积铺展，草地、山地、高原、沙地有自然的尺度关系；
* 湖泊为连续 2~10 格；
* 每条河流都从湖泊边缘出发，最终流入海洋、其他湖泊或已有河流；
* 河流路径使用地势代价搜索，强烈惩罚逆流爬升，整体由高处流向低处；
* 道路不会自然生成。

生成器只依赖 numpy + 标准库，方便在后台线程中运行。
"""

from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .constants import (
    DEFAULT_MAP_SIZE,
    OVERLAY_RIVER,
    OVERLAY_ROAD,
    Terrain,
)
from .edgegeom import cell_path_bank_specs
from .hexmath import NEIGHBORS_EVEN, NEIGHBORS_ODD

ProgressFn = Callable[[int, str], None]


@dataclass
class GenerationResult:
    terrain: bytes
    overlay: bytes
    seed: int
    lake_count: int
    river_count: int
    river_edge_specs: tuple[tuple[tuple[int, int], ...], ...]


class TerrainGenerator:
    def __init__(
        self,
        width: int = DEFAULT_MAP_SIZE,
        height: int = DEFAULT_MAP_SIZE,
        seed: int | None = None,
        *,
        land_ratio: float = 0.34,
        island_amount: float = 0.55,
        lake_amount: float = 0.55,
        river_amount: float = 0.58,
        progress: ProgressFn | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.seed = int(seed if seed is not None else random.SystemRandom().randrange(1, 2_000_000_000))
        self.rng = np.random.default_rng(self.seed)
        self.py_rng = random.Random(self.seed)
        self.land_ratio = float(np.clip(land_ratio, 0.18, 0.55))
        self.island_amount = float(np.clip(island_amount, 0.0, 1.0))
        self.lake_amount = float(np.clip(lake_amount, 0.0, 1.0))
        self.river_amount = float(np.clip(river_amount, 0.0, 1.0))
        self.progress = progress or (lambda _p, _s: None)

        self.terrain = np.zeros((height, width), dtype=np.uint8)
        self.overlay = np.zeros((height, width), dtype=np.uint8)
        self.height_map = np.zeros((height, width), dtype=np.float32)
        self.elevation = np.zeros((height, width), dtype=np.float32)
        self.smooth_height = np.zeros((height, width), dtype=np.float32)
        self.land = np.zeros((height, width), dtype=bool)
        self.moisture = np.zeros((height, width), dtype=np.float32)
        self.ridge = np.zeros((height, width), dtype=np.float32)
        self.detail = np.zeros((height, width), dtype=np.float32)
        self.dist_ocean = np.zeros((height, width), dtype=np.int16)
        self.lake_mask = np.zeros((height, width), dtype=bool)
        self.lake_components: list[list[int]] = []
        self.river_starts: list[int] = []
        self.river_ends: list[int] = []
        self.river_paths: list[list[int]] = []

    # ------------------------------------------------------------------ 公共
    def generate(self) -> GenerationResult:
        self._step(2, "塑造大陆与群岛")
        self._make_land()
        self._step(16, "计算地势与湿度")
        self._make_fields()
        self._step(30, "铺展平原与草地")
        self._paint_lowlands()
        self._step(42, "隆起山脉与高原")
        self._paint_highlands()
        self._step(55, "描绘海岸沙地")
        self._paint_deserts()
        self._step(65, "点缀湖泊")
        self._place_lakes()
        self._step(78, "开凿顺流河道")
        self._carve_rivers()
        self._step(96, "整理地图细节")
        self._finalize()
        self._step(100, "地图生成完成")
        edge_groups: list[tuple[tuple[int, int], ...]] = []
        for path in self.river_paths:
            specs = cell_path_bank_specs(
                path,
                self.width,
                self.height,
                upper=True,
            )
            if specs:
                edge_groups.append(tuple(specs))
        # 河流实体由边链表示；输出覆盖层只保留道路位。
        final_overlay = self.overlay.copy()
        final_overlay &= np.uint8(OVERLAY_ROAD)
        return GenerationResult(
            terrain=self.terrain.tobytes(),
            overlay=final_overlay.tobytes(),
            seed=self.seed,
            lake_count=len(self.lake_components),
            river_count=len(edge_groups),
            river_edge_specs=tuple(edge_groups),
        )

    # ------------------------------------------------------------------ 噪声
    def _step(self, percent: int, text: str) -> None:
        self.progress(percent, text)

    def _value_noise(self, cells: int, rng: np.random.Generator | None = None) -> np.ndarray:
        """平滑的值噪声，输出 0..1。"""
        rng = rng or self.rng
        gw = max(2, cells + 1)
        grid = rng.random((gw, gw), dtype=np.float32)
        xs = np.linspace(0.0, cells, self.width, endpoint=False, dtype=np.float32)
        ys = np.linspace(0.0, cells, self.height, endpoint=False, dtype=np.float32)
        x0 = xs.astype(np.int32)
        y0 = ys.astype(np.int32)
        fx = xs - x0
        fy = ys - y0
        fx = fx * fx * (3.0 - 2.0 * fx)
        fy = fy * fy * (3.0 - 2.0 * fy)
        x1 = np.minimum(x0 + 1, gw - 1)
        y1 = np.minimum(y0 + 1, gw - 1)
        a = grid[y0[:, None], x0[None, :]]
        b = grid[y0[:, None], x1[None, :]]
        c = grid[y1[:, None], x0[None, :]]
        d = grid[y1[:, None], x1[None, :]]
        top = a * (1.0 - fx)[None, :] + b * fx[None, :]
        bot = c * (1.0 - fx)[None, :] + d * fx[None, :]
        return top * (1.0 - fy)[:, None] + bot * fy[:, None]

    def _fbm(
        self,
        cells: int = 4,
        octaves: tuple[int, ...] = (2, 4, 8, 16, 32),
        rng: np.random.Generator | None = None,
    ) -> np.ndarray:
        rng = rng or self.rng
        out = np.zeros((self.height, self.width), dtype=np.float32)
        amp = 1.0
        total = 0.0
        for i, c in enumerate(octaves):
            offset = rng.random(2, dtype=np.float32) * 20.0
            layer = self._value_noise(max(2, c + int(offset[0]) % 3), rng)
            # 旋转一层低频噪声，让轮廓不那么规则。
            if i == 0:
                layer = np.rot90(layer, k=int(offset[1]) % 4)
                layer = np.resize(layer, (self.height, self.width))
            out += layer * amp
            total += amp
            amp *= 0.52
        out /= total
        return np.clip(out, 0.0, 1.0)

    # ------------------------------------------------------------------ 大陆
    def _make_land(self) -> None:
        h, w = self.height, self.width
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        nx = (xx / max(1, w - 1)) * 2.0 - 1.0
        ny = (yy / max(1, h - 1)) * 2.0 - 1.0

        warp = self._fbm(4, (2, 4, 8, 16), np.random.default_rng(self.seed + 17))
        warp = warp * 2.0 - 1.0
        # 大陆轮廓：一个被噪声扭曲的椭圆，避免机械的圆形。
        angle = self.py_rng.uniform(-0.28, 0.28)
        ca, sa = math.cos(angle), math.sin(angle)
        xr = nx * ca - ny * sa
        yr = nx * sa + ny * ca
        radial = np.sqrt((xr / 0.96) ** 2 + (yr / 0.76) ** 2)
        continent = 1.0 - radial + 0.20 * warp

        fine = self._fbm(8, (3, 6, 12, 24, 48, 96), np.random.default_rng(self.seed + 29))
        fine = fine * 2.0 - 1.0
        score = continent + 0.22 * fine
        # 地图边缘留出干净的外海。
        border = np.ones((h, w), dtype=bool)
        edge = max(2, min(w, h) // 120)
        border[:edge, :] = False
        border[-edge:, :] = False
        border[:, :edge] = False
        border[:, -edge:] = False
        candidate = score[border]
        threshold = float(np.quantile(candidate, 1.0 - self.land_ratio))
        mask = (score >= threshold) & border

        # 清理零碎陆地，保留完整主大陆和适量小岛。
        labels, sizes, _ = self._label_components(mask)
        components = [(size, label) for label, size in enumerate(sizes) if size > 0]
        if not components:
            mask = (score >= np.quantile(candidate, 0.6)) & border
            labels, sizes, _ = self._label_components(mask)
            components = [(size, label) for label, size in enumerate(sizes) if size > 0]
        components.sort(reverse=True)
        keep_labels = {components[0][1]} if components else set()

        islands = components[1:]
        self.py_rng.shuffle(islands)
        max_islands = int(round(10 + 22 * self.island_amount))
        kept_islands = 0
        for size, label in islands:
            if kept_islands >= max_islands:
                break
            if size < 2 or size > 90:
                continue
            cells = np.argwhere(labels == label)
            if (
                np.any(cells[:, 0] <= edge)
                or np.any(cells[:, 0] >= h - 1 - edge)
                or np.any(cells[:, 1] <= edge)
                or np.any(cells[:, 1] >= w - 1 - edge)
            ):
                continue
            keep_labels.add(label)
            kept_islands += 1

        self.land = np.isin(labels, list(keep_labels))
        self._add_islands()
        self.terrain[:] = int(Terrain.OCEAN)
        self.terrain[self.land] = int(Terrain.PLAINS)
        self.height_map = score.astype(np.float32)
        self.height_map[~self.land] = -0.35

    def _add_islands(self) -> None:
        """在主大陆之外主动点缀小岛，保证每次生成都有零碎岛屿。"""
        h, w = self.height, self.width
        target = int(round(10 + self.island_amount * 14))
        if target <= 0:
            return
        border = max(3, min(w, h) // 100)
        main = self.land.copy()
        dist_main = self._distance(main, max_distance=32)
        block = self._dilate(self._dilate(main))
        allowed = (
            (~main)
            & (dist_main >= 3)
            & (dist_main <= 24)
        )
        allowed[:border, :] = False
        allowed[-border:, :] = False
        allowed[:, :border] = False
        allowed[:, -border:] = False
        candidates = [(int(r), int(c)) for r, c in np.argwhere(allowed)]
        if not candidates:
            return
        self.py_rng.shuffle(candidates)

        added = 0
        for raw_row, raw_col in candidates:
            if added >= target:
                break
            row, col = int(raw_row), int(raw_col)
            if block[row, col] or main[row, col]:
                continue
            if added == 0:
                target_size = int(round(70 + self.island_amount * 55))
            elif added == 1:
                target_size = int(round(38 + self.island_amount * 38))
            elif added == 2:
                target_size = int(round(20 + self.island_amount * 24))
            else:
                target_size = self.py_rng.choices(
                    [3, 5, 7, 10, 14, 20],
                    weights=[9, 10, 9, 7, 4, 2],
                    k=1,
                )[0]
            cells = self._grow_island(col, row, target_size, allowed, block, main)
            if not cells:
                continue
            for idx in cells:
                rr, cc = divmod(idx, w)
                main[rr, cc] = True
            zone = np.zeros_like(block)
            for idx in cells:
                rr, cc = divmod(idx, w)
                zone[rr, cc] = True
            block = block | self._dilate(self._dilate(zone))
            added += 1
        self.land = main

    def _grow_island(
        self,
        col: int,
        row: int,
        target_size: int,
        allowed: np.ndarray,
        block: np.ndarray,
        main: np.ndarray,
    ) -> list[int]:
        width, height = self.width, self.height
        cells = [row * width + col]
        selected = {cells[0]}
        frontier = [(col, row)]
        while len(cells) < target_size and frontier:
            cc, rr = frontier.pop(self.py_rng.randrange(len(frontier)))
            table = NEIGHBORS_ODD if (rr & 1) else NEIGHBORS_EVEN
            for dc, dr in table:
                nc, nr = cc + dc, rr + dr
                if not (0 <= nc < width and 0 <= nr < height):
                    continue
                if not allowed[nr, nc] or block[nr, nc] or main[nr, nc]:
                    continue
                idx = nr * width + nc
                if idx in selected:
                    continue
                selected.add(idx)
                cells.append(idx)
                frontier.append((nc, nr))
                if len(cells) >= target_size:
                    break
        return cells

    # ------------------------------------------------------------------ 场
    def _make_fields(self) -> None:
        land = self.land
        h = self.height_map.astype(np.float32)
        land_vals = h[land]
        lo = float(np.quantile(land_vals, 0.015))
        hi = float(np.quantile(land_vals, 0.985))
        elev = np.clip((h - lo) / max(1e-6, hi - lo), 0.0, 1.0)
        elev[~land] = 0.0
        self.elevation = elev.astype(np.float32)

        moist = self._fbm(6, (3, 6, 12, 24, 48), np.random.default_rng(self.seed + 41))
        moist = (moist - moist.min()) / max(1e-6, moist.max() - moist.min())
        self.moisture = moist.astype(np.float32)

        ridge_noise = self._fbm(8, (3, 7, 14, 28, 56, 112), np.random.default_rng(self.seed + 53))
        ridge = 1.0 - np.abs(2.0 * ridge_noise - 1.0)
        self.ridge = ridge.astype(np.float32)

        detail = self._fbm(8, (4, 9, 18, 36, 72), np.random.default_rng(self.seed + 67))
        self.detail = detail.astype(np.float32)

        water = ~land
        self.dist_ocean = self._distance(water, max_distance=80)

        # 平滑高度用于河流寻路，避免单格噪声把河道折成锯齿。
        sh = elev.copy()
        for _ in range(2):
            acc = sh.astype(np.float32).copy()
            cnt = np.ones_like(sh, dtype=np.float32)
            for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
                shifted = np.roll(np.roll(sh, dr, axis=0), dc, axis=1)
                acc += shifted
                cnt += 1.0
            sh = acc / cnt
        self.smooth_height = np.where(land, sh, 0.0).astype(np.float32)

    def _distance(self, seeds: np.ndarray, max_distance: int = 80) -> np.ndarray:
        dist = np.full((self.height, self.width), max_distance + 1, dtype=np.int16)
        dist[seeds] = 0
        frontier = seeds.copy()
        for step in range(1, max_distance + 1):
            if not frontier.any():
                break
            grown = self._dilate(frontier)
            new = grown & (~seeds) & (dist > step)
            if not new.any():
                break
            dist[new] = step
            frontier = new
            seeds = seeds | new
        return dist

    @staticmethod
    def _dilate(mask: np.ndarray) -> np.ndarray:
        out = mask.copy()
        out[:, 1:] |= mask[:, :-1]
        out[:, :-1] |= mask[:, 1:]
        out[1:, :] |= mask[:-1, :]
        out[:-1, :] |= mask[1:, :]
        out[1:, 1:] |= mask[:-1, :-1]
        out[1:, :-1] |= mask[:-1, 1:]
        out[:-1, 1:] |= mask[1:, :-1]
        out[:-1, :-1] |= mask[1:, 1:]
        return out

    # ------------------------------------------------------------------ 低地
    def _paint_lowlands(self) -> None:
        land = self.land
        self.terrain[land] = int(Terrain.PLAINS)

        low = self.elevation < 0.62
        grass_score = 0.55 * self.moisture + 0.28 * (1.0 - self.elevation) + 0.17 * self.detail
        grass_thr = float(np.quantile(grass_score[land], 0.53))
        grass = land & low & (grass_score >= grass_thr)
        self.terrain[grass] = int(Terrain.GRASSLAND)

    # ------------------------------------------------------------------ 高地
    def _paint_highlands(self) -> None:
        land = self.land
        elev = self.elevation
        grad_y, grad_x = np.gradient(self.smooth_height)
        rough = np.sqrt(grad_x * grad_x + grad_y * grad_y)
        flatness = 1.0 / (1.0 + rough * 90.0)

        # 高原是高地中相对平缓的核心，先独立选出，不再依赖山地。
        high_enough = elev > float(np.quantile(elev[land], 0.54))
        flat_enough = flatness > 0.24
        plateau_score = 0.58 * flatness + 0.30 * elev + 0.12 * (1.0 - self.detail)
        candidate = land & high_enough & flat_enough
        if candidate.any():
            thr = float(np.quantile(plateau_score[candidate], 0.52))
            plateau = candidate & (plateau_score >= thr)
        else:
            plateau = candidate
        plateau = self._apply_plateaus(plateau, max_size=520, min_size=7)

        # 独立山脊仍由高频噪声产生，但不得侵入高原核心。
        mountain_base = land & (~plateau)
        mountain_score = 0.30 * elev + 0.58 * self.ridge + 0.12 * self.detail
        if mountain_base.any():
            mountain_thr = float(
                np.quantile(mountain_score[mountain_base], 0.825)
            )
            mountain = (
                mountain_base
                & (elev > 0.37)
                & (mountain_score >= mountain_thr)
            )
            mountain = self._apply_mountains(mountain, max_size=1500)
        else:
            mountain = np.zeros_like(land)

        # 山地包裹高原：沿高原外缘生成两格连续山地环，再叠加独立山脊。
        if plateau.any():
            rim = self._dilate(plateau) & land & (~plateau)
            rim = self._dilate(rim) & land & (~plateau)
            mountain |= rim

        self.terrain[plateau] = int(Terrain.PLATEAU)
        self.terrain[mountain] = int(Terrain.MOUNTAIN)

    def _apply_mountains(self, mountain: np.ndarray, max_size: int) -> np.ndarray:
        """限制独立山地连通块大小，并把削去的边缘变成低地。"""
        labels, sizes, _ = self._label_components(mountain)
        limited = mountain.copy()
        released = np.zeros_like(mountain)
        for label, size in enumerate(sizes):
            if size <= max_size:
                continue
            comp = labels == label
            working = comp.copy()
            while int(working.sum()) > max_size:
                boundary = working & self._dilate(~working)
                if not boundary.any():
                    break
                working[boundary] = False
                released[boundary] = True
            limited[comp] = working[comp]
        self.terrain[released] = np.where(
            self.moisture[released] > 0.48,
            np.uint8(Terrain.GRASSLAND),
            np.uint8(Terrain.PLAINS),
        )
        self.terrain[limited] = int(Terrain.MOUNTAIN)
        return limited

    def _apply_plateaus(
        self,
        plateau: np.ndarray,
        *,
        max_size: int,
        min_size: int,
    ) -> np.ndarray:
        """限制高原连通块大小；高原本身是被山地环绕的高而平缓核心。"""
        labels, sizes, _ = self._label_components(plateau)
        result = plateau.copy()
        for label, size in enumerate(sizes):
            if size == 0:
                continue
            comp = labels == label
            if size < min_size:
                result[comp] = False
                continue
            if size > max_size:
                working = comp.copy()
                while int(working.sum()) > max_size:
                    boundary = working & self._dilate(~working)
                    if not boundary.any():
                        break
                    working[boundary] = False
                result[comp] = working[comp]
        dropped = plateau & ~result
        self.terrain[dropped] = np.where(
            self.moisture[dropped] > 0.48,
            np.uint8(Terrain.GRASSLAND),
            np.uint8(Terrain.PLAINS),
        )
        self.terrain[result] = int(Terrain.PLATEAU)
        return result

    # ------------------------------------------------------------------ 沙地
    def _paint_deserts(self) -> None:
        land = self.land
        elev = self.elevation
        moisture = self.moisture
        dry = 0.60 * self.detail + 0.40 * (1.0 - moisture)
        coast = (self.dist_ocean >= 1) & (self.dist_ocean <= 3)
        if coast.any():
            thr = float(np.quantile(dry[coast], 0.42))
            beach = land & coast & (dry >= thr) & (elev < 0.58)
        else:
            beach = np.zeros_like(land)
        # 内陆大型沙地 / 零星沙丘。
        inland_thr = float(np.quantile(dry[land], 0.935))
        inland = land & (dry >= inland_thr) & (elev < 0.52) & (self.dist_ocean > 2)
        desert = beach | inland
        blocked = (
            (self.terrain == int(Terrain.MOUNTAIN))
            | (self.terrain == int(Terrain.PLATEAU))
            | (self.terrain == int(Terrain.LAKE))
            | (~land)
        )
        desert &= ~blocked
        self.terrain[desert] = int(Terrain.DESERT)

    # ------------------------------------------------------------------ 湖泊
    def _place_lakes(self) -> None:
        if self.lake_amount <= 0.01:
            return
        land = self.land
        water = np.zeros_like(land)
        target_count = int(round(8 + self.lake_amount * 18))
        candidates = (
            land
            & (self.dist_ocean >= 3)
            & (self.elevation > 0.08)
            & (self.terrain != int(Terrain.MOUNTAIN))
            & (self.terrain != int(Terrain.PLATEAU))
        )
        candidate_indices = list(map(int, np.flatnonzero(candidates)))
        self.py_rng.shuffle(candidate_indices)
        lake_zone = np.zeros_like(land)

        placed = 0
        for raw_index in candidate_indices:
            if placed >= target_count:
                break
            row, col = divmod(raw_index, self.width)
            if lake_zone[row, col]:
                continue
            if self.lake_mask[row, col] or water[row, col]:
                continue
            highland = self.elevation[row, col] > 0.35
            local_basin = self._local_basin(row, col)
            if highland and not local_basin:
                continue
            target_size = self.py_rng.randint(3, 10)
            cells = self._grow_lake(col, row, target_size)
            if len(cells) < 2:
                continue
            # 湖与湖之间至少隔一格，避免视觉上连成超过 10 格的湖群。
            for idx in cells:
                rr, cc = divmod(idx, self.width)
                self.lake_mask[rr, cc] = True
                self.terrain[rr, cc] = int(Terrain.LAKE)
                lake_zone[rr, cc] = True
                lake_zone[max(0, rr - 1) : min(self.height, rr + 2), max(0, cc - 2) : min(self.width, cc + 3)] = True
            placed += 1

        labels, sizes, _ = self._label_components(self.terrain == int(Terrain.LAKE))
        self.lake_components = []
        for label, size in enumerate(sizes):
            if size > 0:
                cells = list(map(int, np.flatnonzero(labels == label)))
                self.lake_components.append(cells)

    def _local_basin(self, row: int, col: int) -> bool:
        center = float(self.smooth_height[row, col])
        table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
        values = []
        for dc, dr in table:
            nc, nr = col + dc, row + dr
            if 0 <= nc < self.width and 0 <= nr < self.height:
                values.append(float(self.smooth_height[nr, nc]))
        if not values:
            return False
        return center <= float(np.mean(values)) + 0.008

    def _grow_lake(self, col: int, row: int, target_size: int) -> list[int]:
        width = self.width
        cells = [row * width + col]
        selected = {cells[0]}
        frontier = self._lake_frontier(col, row, selected)
        while len(cells) < target_size and frontier:
            # 随机挑 2~3 个候选中的最低处，湖面会略呈自然形状。
            sample = self.py_rng.sample(frontier, min(len(frontier), 3))
            best = min(
                sample,
                key=lambda p: (
                    float(self.smooth_height[p[1], p[0]]) + self.py_rng.random() * 0.025
                ),
            )
            frontier.remove(best)
            cc, rr = best
            idx = rr * width + cc
            if idx in selected:
                continue
            if not self._lake_cell_ok(cc, rr):
                continue
            selected.add(idx)
            cells.append(idx)
            frontier.extend(self._lake_frontier(cc, rr, selected))
            # 去重并剔除不可用项。
            frontier = [p for p in dict.fromkeys(frontier) if p not in {(i % width, i // width) for i in selected}]
            frontier = [p for p in frontier if self._lake_cell_ok(*p)]
        return cells

    def _lake_frontier(self, col: int, row: int, selected: set[int]) -> list[tuple[int, int]]:
        out = []
        table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
        for dc, dr in table:
            nc, nr = col + dc, row + dr
            if 0 <= nc < self.width and 0 <= nr < self.height:
                if nr * self.width + nc not in selected:
                    out.append((nc, nr))
        return out

    def _lake_cell_ok(self, col: int, row: int) -> bool:
        if not (0 <= col < self.width and 0 <= row < self.height):
            return False
        if not self.land[row, col]:
            return False
        if self.lake_mask[row, col]:
            return False
        if self.dist_ocean[row, col] < 2:
            return False
        terrain = int(self.terrain[row, col])
        if terrain in (int(Terrain.MOUNTAIN), int(Terrain.PLATEAU)):
            return False
        return True

    # ------------------------------------------------------------------ 河流
    def _carve_rivers(self) -> None:
        if self.river_amount <= 0.01 or not self.lake_components:
            return
        # 高处的湖泊优先作为河源；低地湖泊也可能形成短河。
        scored = []
        for cells in self.lake_components:
            mean_e = float(np.mean([self.elevation[i // self.width, i % self.width] for i in cells]))
            mean_dist = float(np.mean([self.dist_ocean[i // self.width, i % self.width] for i in cells]))
            score = mean_e * 1.5 + min(mean_dist, 25) / 25.0
            scored.append((score, cells))
        scored.sort(reverse=True, key=lambda item: item[0])
        target = int(round(4 + self.river_amount * 7))
        for _score, lake_cells in scored:
            if len(self.river_starts) >= target:
                break
            self._route_from_lake(lake_cells)

    def _route_from_lake(self, lake_cells: list[int]) -> bool:
        source_set = set(lake_cells)
        world_w = self.width
        outlet_candidates: list[tuple[float, int]] = []
        seen = set()
        for idx in lake_cells:
            row, col = divmod(idx, world_w)
            table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
            for dc, dr in table:
                nc, nr = col + dc, row + dr
                if not (0 <= nc < self.width and 0 <= nr < self.height):
                    continue
                nidx = nr * world_w + nc
                if nidx in source_set or nidx in seen:
                    continue
                if not self.land[nr, nc] or self.lake_mask[nr, nc]:
                    continue
                if self.overlay[nr, nc] & OVERLAY_RIVER:
                    continue
                seen.add(nidx)
                outlet_candidates.append((float(self.smooth_height[nr, nc]), nidx))
        outlet_candidates.sort()
        # 每个湖最多尝试三个出口，避免寻路过久。
        for _h, start in outlet_candidates[:3]:
            path = self._astar_to_water(start, source_set)
            if path is None or len(path) < 6:
                continue
            # 起点的相邻格应为湖泊，终点应邻接海洋/其他湖泊/已有河流。
            if not self._is_adjacent_to_mask(start, self.lake_mask):
                continue
            if not self._valid_water_end(path[-1], source_set):
                continue
            # 强制河流整体由高处流向低处，且不允许长距离逆流爬升。
            heights = [
                float(self.smooth_height[idx // world_w, idx % world_w]) for idx in path
            ]
            start_h, end_h = heights[0], heights[-1]
            drop = start_h - end_h
            ascent = sum(max(0.0, b - a) for a, b in zip(heights, heights[1:]))
            if drop < 0.015:
                continue
            if ascent > 1e-6:
                continue
            for idx in path:
                row, col = divmod(idx, world_w)
                self.overlay[row, col] |= OVERLAY_RIVER
            self.river_starts.append(start)
            self.river_ends.append(path[-1])
            self.river_paths.append(path)
            return True
        return False

    def _astar_to_water(self, start: int, source_lake: set[int]) -> list[int] | None:
        """从湖口出发，沿地势寻路到海洋、其他湖泊或已有河流。

        代价对逆流爬升有极强惩罚，整体路径必定从高处倾向低处。
        到达海洋/湖泊/河流前的最后一个陆地格即为终点。
        """
        width, height = self.width, self.height
        n = width * height
        if self.dist_ocean[start // width, start % width] <= 0:
            return None
        start_row, start_col = divmod(start, width)

        import numpy as _np

        source_mask = self._mask_from_set(source_lake)
        ocean_mask = ~self.land
        other_lakes = self.lake_mask & ~source_mask
        river_mask = (self.overlay & OVERLAY_RIVER) != 0

        gscore = _np.full(n, _np.inf, dtype=_np.float32)
        parent = _np.full(n, -1, dtype=_np.int32)
        gscore[start] = 0.0
        open_heap: list[tuple[float, int]] = []
        dist_h = self.dist_ocean.astype(_np.float32)
        noise = self.detail
        heapq.heappush(open_heap, (float(dist_h[start_row, start_col]) * 0.22, start))
        closed = bytearray(n)
        found: int | None = None
        budget = 0

        while open_heap:
            _f, current = heapq.heappop(open_heap)
            if closed[current]:
                continue
            closed[current] = 1
            budget += 1
            if budget > 160_000:
                break
            row, col = divmod(current, width)
            if current != start:
                if river_mask[row, col] or (self.overlay[row, col] & OVERLAY_ROAD):
                    found = current
                    break
                if self._is_adjacent_to_mask(current, other_lakes):
                    found = current
                    break
                if self._is_adjacent_to_mask(current, ocean_mask):
                    found = current
                    break
            table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
            base_g = float(gscore[current])
            for dc, dr in table:
                nc, nr = col + dc, row + dr
                if not (0 <= nc < self.width and 0 <= nr < self.height):
                    continue
                nidx = nr * width + nc
                if closed[nidx]:
                    continue
                if not self.land[nr, nc] or self.lake_mask[nr, nc]:
                    continue
                if nidx in source_lake:
                    continue
                dh = float(self.smooth_height[nr, nc]) - float(self.smooth_height[row, col])
                uphill = max(0.0, dh)
                step = (
                    1.0
                    + uphill * 240.0
                    + abs(dh) * 4.0
                    + float(noise[nr, nc]) * 0.55
                    + (0.6 if self.terrain[nr, nc] == int(Terrain.MOUNTAIN) else 0.0)
                )
                tentative = base_g + step
                if tentative >= float(gscore[nidx]):
                    continue
                gscore[nidx] = tentative
                parent[nidx] = current
                heuristic = float(dist_h[nr, nc]) * 0.22
                heapq.heappush(open_heap, (tentative + heuristic, nidx))

        if found is None:
            return None
        path: list[int] = []
        node = found
        while node != -1:
            path.append(node)
            if node == start:
                break
            node = int(parent[node])
        path.reverse()
        if not path or path[0] != start:
            return None
        path = [idx for idx in path if self.land[idx // width, idx % width]]
        if not path:
            return None
        if self._path_crosses_source_lake(path, source_lake):
            return None
        return path

    def _mask_from_set(self, cells: set[int]) -> np.ndarray:
        mask = np.zeros((self.height, self.width), dtype=bool)
        for idx in cells:
            row, col = divmod(idx, self.width)
            mask[row, col] = True
        return mask

    def _path_crosses_source_lake(self, path: list[int], source_lake: set[int]) -> bool:
        return any(idx in source_lake for idx in path)

    def _is_adjacent_to_mask(self, index: int, mask: np.ndarray) -> bool:
        row, col = divmod(index, self.width)
        table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
        for dc, dr in table:
            nc, nr = col + dc, row + dr
            if 0 <= nc < self.width and 0 <= nr < self.height and mask[nr, nc]:
                return True
        return False

    def _valid_water_end(self, index: int, source_lake: set[int]) -> bool:
        row, col = divmod(index, self.width)
        if self.overlay[row, col] & OVERLAY_RIVER:
            return True
        source_mask = self._mask_from_set(source_lake)
        other_lakes = self.lake_mask & ~source_mask
        if self._is_adjacent_to_mask(index, ~self.land):
            return True
        if self._is_adjacent_to_mask(index, other_lakes):
            return True
        if self._is_adjacent_to_mask(index, (self.overlay & OVERLAY_RIVER) != 0):
            return True
        return False

    # ------------------------------------------------------------------ 整理
    def _finalize(self) -> None:
        # 清除意外落在水格上的河流/道路覆盖。
        water = (self.terrain == int(Terrain.OCEAN)) | (self.terrain == int(Terrain.LAKE))
        self.overlay[water] = 0
        # 道路不自然生成。
        self.overlay &= np.uint8(OVERLAY_RIVER)

        # 湖泊不应该贴着海洋；若生成器在极窄地峡处造成这种情况，把它还原为草地。
        lake = self.terrain == int(Terrain.LAKE)
        if lake.any():
            ocean_near = lake & self._dilate(self.terrain == int(Terrain.OCEAN))
            self.terrain[ocean_near] = int(Terrain.GRASSLAND)

        # 再确保每个湖泊连通块不超过 10 格。
        lake = self.terrain == int(Terrain.LAKE)
        labels, sizes, _ = self._label_components(lake)
        for label, size in enumerate(sizes):
            if size > 10:
                cells = np.argwhere(labels == label)
                # 保留最靠近地图中心/内陆的 10 格，其余还原为草地。
                cells_list = sorted(
                    [(int(r), int(c)) for r, c in cells],
                    key=lambda rc: -int(self.dist_ocean[rc[0], rc[1]]),
                )
                for r, c in cells_list[10:]:
                    self.terrain[r, c] = int(Terrain.GRASSLAND)

    # ------------------------------------------------------------------ 连通
    def _label_components(self, mask: np.ndarray) -> tuple[np.ndarray, list[int], int]:
        """六邻接连通块标记，返回 (labels, sizes, count)。"""
        h, w = mask.shape
        labels = np.full((h, w), -1, dtype=np.int32)
        sizes: list[int] = []
        flat_labels = labels.reshape(-1)
        flat_mask = mask.reshape(-1)
        next_label = 0
        indices = np.flatnonzero(flat_mask)
        for start in indices:
            s = int(start)
            if flat_labels[s] != -1:
                continue
            label = next_label
            next_label += 1
            flat_labels[s] = label
            stack = [s]
            count = 0
            while stack:
                idx = stack.pop()
                count += 1
                row, col = divmod(idx, w)
                table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
                for dc, dr in table:
                    nc, nr = col + dc, row + dr
                    if nc < 0 or nc >= w or nr < 0 or nr >= h:
                        continue
                    nidx = nr * w + nc
                    if flat_labels[nidx] != -1 or not flat_mask[nidx]:
                        continue
                    flat_labels[nidx] = label
                    stack.append(nidx)
            sizes.append(count)
        return labels, sizes, next_label
