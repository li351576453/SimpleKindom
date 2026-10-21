"""核心规则测试。

运行：
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib

import numpy as np

from simplekingdom.constants import (
    OVERLAY_RIVER,
    OVERLAY_ROAD,
    Terrain,
)
from simplekingdom.edgegeom import (
    adjacent_edge_choices,
    cell_center_world,
    cell_path_bank_specs,
    edge_vertex_keys,
    nearest_vertex_of_cell,
    vertex_path,
)
from simplekingdom.generator import TerrainGenerator
from simplekingdom.hexmath import (
    NEIGHBORS_EVEN,
    NEIGHBORS_ODD,
)
from simplekingdom.model import MapModel
from simplekingdom.storage import HEADER, MAGIC, load_map, save_map


def neighbors_of(model: MapModel, col: int, row: int):
    table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
    for dc, dr in table:
        nc, nr = col + dc, row + dr
        if 0 <= nc < model.width and 0 <= nr < model.height:
            yield nc, nr


class HexAndPathTests(unittest.TestCase):
    def test_initially_all_ocean(self) -> None:
        model = MapModel(20, 20)
        self.assertTrue(all(value == int(Terrain.OCEAN) for value in model.terrain))

    def test_legacy_cell_road_becomes_edge_chain(self) -> None:
        model = MapModel(10, 10)
        cells = [(2, 2), (3, 2), (4, 2)]
        for col, row in cells:
            model.overlay[model.index(col, row)] = OVERLAY_ROAD
        model.rebuild_all_edges()
        self.assertEqual(len(model.road_groups), 1)
        self.assertGreater(len(model.road_groups[0]), 0)
        self.assertGreater(
            sum(mask.bit_count() for mask in model.road_edges),
            0,
        )

    def test_road_edges_are_independent_groups(self) -> None:
        model = MapModel(30, 30)
        first_cells = [
            model.index(col, row) for col, row in [(3, 8), (4, 8), (5, 8), (6, 8)]
        ]
        second_cells = [
            model.index(col, row) for col, row in [(5, 8), (5, 9), (6, 10), (7, 10)]
        ]
        first_specs = cell_path_bank_specs(
            first_cells, model.width, model.height, upper=True
        )
        second_specs = cell_path_bank_specs(
            second_cells, model.width, model.height, upper=True
        )
        self.assertTrue(model.add_road_edge_group(first_specs))
        self.assertTrue(model.add_road_edge_group(second_specs))
        model.rebuild_all_edges()
        self.assertEqual(len(model.road_groups), 2)
        self.assertGreater(
            sum(mask.bit_count() for mask in model.road_edges),
            0,
        )

    def test_legacy_cell_river_becomes_edge_chain(self) -> None:
        model = MapModel(10, 10)
        cells = [(2, 2), (3, 2), (4, 2)]
        for col, row in cells:
            model.overlay[model.index(col, row)] = OVERLAY_RIVER
        model.rebuild_all_edges()
        # 旧版格子河流会自动转换为一条外岸边链。
        self.assertEqual(len(model.river_groups), 1)
        self.assertGreater(len(model.river_groups[0]), 0)
        self.assertGreater(
            sum(mask.bit_count() for mask in model.river_edges),
            0,
        )
        self.assertTrue(model.river_curvatures)

    def test_edge_owner_is_inner_side(self) -> None:
        model = MapModel(30, 30)
        cells = [
            model.index(col, row)
            for col, row in [(5, 8), (6, 8), (7, 8), (8, 8), (8, 9), (8, 10)]
        ]
        specs = cell_path_bank_specs(cells, model.width, model.height, upper=True)
        self.assertTrue(model.add_river_edge_group(specs))
        model.rebuild_all_edges()
        info = model.river_curvatures[0]
        self.assertIsNotNone(info.selected)
        self.assertEqual(
            info.selected.radius,
            max(circle.radius for circle in info.circles),
        )
        for owner, edge in model.river_groups[0]:
            choices = adjacent_edge_choices(owner, edge, model.width, model.height)
            self.assertIn((owner, edge), choices)
            owner_x, owner_y = cell_center_world(owner, model.width)
            owner_distance = (
                (owner_x - info.selected.center_x) ** 2
                + (owner_y - info.selected.center_y) ** 2
            )
            for other, other_edge in choices:
                if (other, other_edge) == (owner, edge):
                    continue
                other_x, other_y = cell_center_world(other, model.width)
                other_distance = (
                    (other_x - info.selected.center_x) ** 2
                    + (other_y - info.selected.center_y) ** 2
                )
                self.assertLessEqual(owner_distance, other_distance + 1e-9)

    def test_river_and_road_can_share_cell(self) -> None:
        model = MapModel(10, 10)
        idx = model.index(4, 4)
        self.assertTrue(model.add_road_edge_group([(idx, 0)]))
        self.assertTrue(model.add_river_edge_group([(idx, 0)]))
        model.rebuild_all_edges()
        self.assertTrue(model.road_edges[idx] & (1 << 0))
        self.assertTrue(model.river_edges[idx] & (1 << 0))
        self.assertTrue(model.overlay[idx] & OVERLAY_ROAD)
        self.assertTrue(model.overlay[idx] & OVERLAY_RIVER)

    def test_vertex_path_builds_continuous_edge_chain(self) -> None:
        width, height = 40, 40
        start, start_point = nearest_vertex_of_cell(
            width * 10 + 10, 11.0, 15.0, width
        )
        end, end_point = nearest_vertex_of_cell(
            width * 14 + 12, 20.0, 18.0, width
        )
        self.assertNotEqual(start, end)
        self.assertNotEqual(start_point, end_point)
        edges = vertex_path(start, end, width, height)
        self.assertIsNotNone(edges)
        assert edges is not None
        self.assertGreaterEqual(len(edges), 2)
        self.assertIn(start, edge_vertex_keys(*edges[0], width))
        self.assertIn(end, edge_vertex_keys(*edges[-1], width))
        for first, second in zip(edges, edges[1:]):
            self.assertTrue(
                set(edge_vertex_keys(*first, width))
                & set(edge_vertex_keys(*second, width)),
                "路径点连线必须首尾相接",
            )

    def test_vertex_path_can_build_a_road_group(self) -> None:
        width, height = 40, 40
        start, _ = nearest_vertex_of_cell(width * 10 + 10, 11.0, 15.0, width)
        end, _ = nearest_vertex_of_cell(width * 14 + 12, 20.0, 18.0, width)
        edges = vertex_path(start, end, width, height)
        self.assertIsNotNone(edges)
        assert edges is not None
        model = MapModel(width, height)
        self.assertTrue(model.add_road_edge_group(edges))
        model.rebuild_all_edges()
        self.assertEqual(len(model.road_groups), 1)
        self.assertEqual(len(model.river_groups), 0)
        self.assertGreater(
            sum(mask.bit_count() for mask in model.road_edges),
            0,
        )

    def test_tributary_is_independent_from_main_river(self) -> None:
        model = MapModel(30, 30)
        main_cells = [
            model.index(col, row) for col, row in [(3, 8), (4, 8), (5, 8), (6, 8)]
        ]
        tributary_cells = [
            model.index(col, row) for col, row in [(5, 8), (5, 9), (6, 10), (7, 10)]
        ]
        main_specs = cell_path_bank_specs(
            main_cells, model.width, model.height, upper=True
        )
        tributary_specs = cell_path_bank_specs(
            tributary_cells, model.width, model.height, upper=True
        )
        self.assertTrue(model.add_river_edge_group(main_specs))
        self.assertTrue(model.add_river_edge_group(tributary_specs))
        model.rebuild_all_edges()
        self.assertEqual(len(model.river_groups), 2)
        self.assertEqual(len(model.river_curvatures), 2)
        self.assertGreater(len(model.river_groups[0]), 0)
        self.assertGreater(len(model.river_groups[1]), 0)

    def test_remove_river_edges_prunes_groups(self) -> None:
        model = MapModel(20, 20)
        cells = [model.index(col, 5) for col in range(2, 8)]
        specs = cell_path_bank_specs(cells, model.width, model.height, upper=True)
        self.assertTrue(model.add_river_edge_group(specs))
        model.rebuild_all_edges()
        self.assertEqual(len(model.river_groups), 1)
        initial_edges = sum(mask.bit_count() for mask in model.river_edges)
        self.assertGreater(initial_edges, 1)

        self.assertTrue(model.remove_river_edges([specs[0]]))
        model.rebuild_all_edges()
        self.assertEqual(len(model.river_groups), 1)
        self.assertLess(
            sum(mask.bit_count() for mask in model.river_edges),
            initial_edges,
        )

        remaining = [
            (owner, edge)
            for group in model.river_groups
            for owner, edge in group
        ]
        self.assertTrue(model.remove_river_edges(remaining))
        model.rebuild_all_edges()
        self.assertEqual(len(model.river_groups), 0)
        self.assertEqual(sum(mask.bit_count() for mask in model.river_edges), 0)

    def test_remove_road_edges_prunes_groups(self) -> None:
        model = MapModel(20, 20)
        cells = [model.index(col, 5) for col in range(2, 8)]
        specs = cell_path_bank_specs(cells, model.width, model.height, upper=True)
        self.assertTrue(model.add_road_edge_group(specs))
        model.rebuild_all_edges()
        self.assertEqual(len(model.road_groups), 1)
        remaining = [
            (owner, edge)
            for group in model.road_groups
            for owner, edge in group
        ]
        self.assertTrue(model.remove_road_edges(remaining))
        model.rebuild_all_edges()
        self.assertEqual(len(model.road_groups), 0)
        self.assertEqual(sum(mask.bit_count() for mask in model.road_edges), 0)


class GeneratorRuleTests(unittest.TestCase):
    SEEDS = (1, 42, 123456)

    def _assert_adjacent_lake(self, gen: TerrainGenerator, index: int) -> None:
        row, col = divmod(index, gen.width)
        found = False
        for dc, dr in (NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN):
            nc, nr = col + dc, row + dr
            if 0 <= nc < gen.width and 0 <= nr < gen.height:
                if gen.terrain[nr, nc] == int(Terrain.LAKE):
                    found = True
                    break
        self.assertTrue(found, "河流起点必须紧邻湖泊")

    def _assert_valid_end(self, gen: TerrainGenerator, index: int) -> None:
        row, col = divmod(index, gen.width)
        found = False
        for dc, dr in (NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN):
            nc, nr = col + dc, row + dr
            if not (0 <= nc < gen.width and 0 <= nr < gen.height):
                continue
            terrain = gen.terrain[nr, nc]
            if (
                terrain in (int(Terrain.OCEAN), int(Terrain.LAKE))
                or (gen.overlay[nr, nc] & OVERLAY_RIVER)
            ):
                found = True
                break
        self.assertTrue(found, "河流终点必须接海洋、湖泊或既有河流")

    def test_generation_rules(self) -> None:
        for seed in self.SEEDS:
            with self.subTest(seed=seed):
                gen = TerrainGenerator(seed=seed)
                result = gen.generate()
                land = gen.land
                labels, sizes, _ = gen._label_components(land)
                sizes = [s for s in sizes if s > 0]
                self.assertGreaterEqual(len(sizes), 5, "应包含主大陆与零碎小岛")
                self.assertGreater(max(sizes), sum(sizes) * 0.85, "必须存在完整主大陆")

                lake_labels, lake_sizes, _ = gen._label_components(
                    gen.terrain == int(Terrain.LAKE)
                )
                self.assertTrue(all(size <= 10 for size in lake_sizes), "湖泊不得超过 10 格")
                for size in lake_sizes:
                    self.assertGreater(size, 0)

                overlay = np.frombuffer(result.overlay, dtype=np.uint8)
                self.assertEqual(int(np.count_nonzero(overlay & OVERLAY_ROAD)), 0)

                self.assertGreaterEqual(len(gen.river_paths), 4)
                self.assertGreaterEqual(len(result.river_edge_specs), 4)
                for start, end, path in zip(
                    gen.river_starts, gen.river_ends, gen.river_paths
                ):
                    self._assert_adjacent_lake(gen, start)
                    self._assert_valid_end(gen, end)
                    heights = [
                        float(gen.smooth_height[idx // gen.width, idx % gen.width])
                        for idx in path
                    ]
                    for a, b in zip(heights, heights[1:]):
                        self.assertLessEqual(
                            b,
                            a + 1e-6,
                            "河流必须从高处流向低处，不允许逆流",
                        )

                counts = np.bincount(
                    np.frombuffer(result.terrain, dtype=np.uint8), minlength=7
                )
                self.assertGreater(counts[int(Terrain.PLAINS)], 1000)
                self.assertGreater(counts[int(Terrain.GRASSLAND)], 1000)
                self.assertGreater(counts[int(Terrain.MOUNTAIN)], 100)
                self.assertGreater(counts[int(Terrain.PLATEAU)], 100)
                self.assertGreater(counts[int(Terrain.DESERT)], 100)

                plateau_labels, plateau_sizes, _ = gen._label_components(
                    gen.terrain == int(Terrain.PLATEAU)
                )
                for label, size in enumerate(plateau_sizes):
                    if size < 7:
                        continue
                    comp = plateau_labels == label
                    boundary = gen._dilate(comp) & (~comp) & gen.land
                    total = int(boundary.sum())
                    if total == 0:
                        continue
                    mountain = int(
                        (boundary & (gen.terrain == int(Terrain.MOUNTAIN))).sum()
                    )
                    self.assertGreaterEqual(
                        mountain / total,
                        0.6,
                        "高原外围应由山地包裹",
                    )

    def test_same_seed_is_reproducible(self) -> None:
        first = TerrainGenerator(seed=2024).generate()
        second = TerrainGenerator(seed=2024).generate()
        self.assertEqual(first.terrain, second.terrain)
        self.assertEqual(first.overlay, second.overlay)
        self.assertEqual(first.river_edge_specs, second.river_edge_specs)

    def test_generated_river_specs_build_independent_edge_chains(self) -> None:
        result = TerrainGenerator(seed=123456).generate()
        model = MapModel(500, 500)
        model.set_arrays(result.terrain, result.overlay)
        for specs in result.river_edge_specs:
            self.assertTrue(model.add_river_edge_group(specs))
        model.rebuild_all_edges()
        self.assertEqual(len(model.river_groups), len(result.river_edge_specs))
        self.assertGreaterEqual(len(model.river_groups), 4)
        self.assertGreater(
            sum(mask.bit_count() for mask in model.river_edges),
            0,
        )


class StorageTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        model = MapModel(64, 48)
        model.name = "测试大陆"
        model.seed = 998877
        for i in range(0, model.cell_count, 17):
            model.terrain[i] = int(Terrain.GRASSLAND)
        model.overlay[model.index(3, 4)] = OVERLAY_ROAD
        self.assertTrue(model.add_river_edge_group([(model.index(3, 4), 0)]))
        model.rebuild_all_edges()

        fd, path = tempfile.mkstemp(suffix=".skmap")
        os.close(fd)
        try:
            save_map(model, path)
            loaded, snapshot = load_map(path)
            self.assertEqual(loaded.width, 64)
            self.assertEqual(loaded.height, 48)
            self.assertEqual(loaded.name, "测试大陆")
            self.assertEqual(loaded.seed, 998877)
            self.assertEqual(loaded.terrain, model.terrain)
            self.assertEqual(loaded.overlay, model.overlay)
            self.assertEqual(len(snapshot.terrain), model.cell_count)
            self.assertNotEqual(loaded.road_edges[model.index(3, 4)], 0)
            self.assertEqual(loaded.river_edges, model.river_edges)
            self.assertEqual(loaded.road_edges, model.road_edges)
            self.assertEqual(loaded.copy_river_groups(), model.copy_river_groups())
            self.assertEqual(loaded.copy_road_groups(), model.copy_road_groups())
        finally:
            os.unlink(path)

    def test_roundtrip_preserves_independent_tributary_groups(self) -> None:
        model = MapModel(40, 30)
        main_cells = [model.index(col, 5) for col in range(4, 14)]
        tributary_cells = [model.index(8, 5)] + [
            model.index(8, row) for row in range(6, 11)
        ]
        for cells in (main_cells, tributary_cells):
            specs = cell_path_bank_specs(
                cells, model.width, model.height, upper=True
            )
            self.assertTrue(model.add_river_edge_group(specs))
        road_cells = [model.index(col, 15) for col in range(4, 10)]
        road_specs = cell_path_bank_specs(
            road_cells, model.width, model.height, upper=True
        )
        self.assertTrue(model.add_road_edge_group(road_specs))
        model.rebuild_all_edges()
        before_groups = model.copy_river_groups()
        before_roads = model.copy_road_groups()
        self.assertEqual(len(before_groups), 2)
        self.assertEqual(len(before_roads), 1)

        fd, path = tempfile.mkstemp(suffix=".skmap")
        os.close(fd)
        try:
            save_map(model, path)
            loaded, snapshot = load_map(path)
            self.assertEqual(loaded.overlay, model.overlay)
            self.assertEqual(loaded.copy_river_groups(), before_groups)
            self.assertEqual(loaded.copy_road_groups(), before_roads)
            self.assertEqual(loaded.river_edges, model.river_edges)
            self.assertEqual(loaded.road_edges, model.road_edges)
            self.assertEqual(len(loaded.river_curvatures), 2)
            self.assertEqual(snapshot.river_groups, before_groups)
            self.assertEqual(snapshot.road_groups, before_roads)
        finally:
            os.unlink(path)

    def test_version3_road_overlay_is_migrated_to_edge_chain(self) -> None:
        width, height = 20, 20
        terrain = bytes([int(Terrain.GRASSLAND)]) * (width * height)
        road_cells = [row * width + 10 for row in range(4, 10)]
        overlay = bytearray(width * height)
        for idx in road_cells:
            overlay[idx] |= OVERLAY_ROAD
        decoded = terrain + bytes(overlay) + struct.pack(">I", 0)
        packed = zlib.compress(decoded)
        name = b"legacy-v3"
        header = HEADER.pack(
            MAGIC,
            3,
            width,
            height,
            12345,
            len(name),
            len(packed),
        )
        fd, path = tempfile.mkstemp(suffix=".skmap")
        os.close(fd)
        try:
            with open(path, "wb") as handle:
                handle.write(header + name + packed)
            loaded, _ = load_map(path)
            self.assertEqual(len(loaded.road_groups), 1)
            self.assertGreater(
                sum(mask.bit_count() for mask in loaded.road_edges),
                0,
            )
            self.assertEqual(len(loaded.river_groups), 0)
        finally:
            os.unlink(path)

    def test_version2_cell_groups_are_migrated_to_edge_chains(self) -> None:
        width, height = 20, 20
        terrain = bytes([int(Terrain.GRASSLAND)]) * (width * height)
        river_cells = [row * width + 5 for row in range(4, 10)]
        road_cells = [row * width + 10 for row in range(4, 10)]
        overlay = bytearray(width * height)
        for idx in river_cells:
            overlay[idx] |= OVERLAY_RIVER
        for idx in road_cells:
            overlay[idx] |= OVERLAY_ROAD
        group_data = (
            struct.pack(">I", 1)
            + struct.pack(">I", len(river_cells))
            + struct.pack(f">{len(river_cells)}I", *river_cells)
        )
        packed = zlib.compress(terrain + bytes(overlay) + group_data)
        name = b"legacy-v2"
        header = HEADER.pack(
            MAGIC,
            2,
            width,
            height,
            12345,
            len(name),
            len(packed),
        )
        fd, path = tempfile.mkstemp(suffix=".skmap")
        os.close(fd)
        try:
            with open(path, "wb") as handle:
                handle.write(header + name + packed)
            loaded, snapshot = load_map(path)
            self.assertEqual(len(loaded.river_groups), 1)
            self.assertGreater(
                sum(mask.bit_count() for mask in loaded.river_edges),
                0,
            )
            self.assertEqual(len(loaded.road_groups), 1)
            self.assertGreater(
                sum(mask.bit_count() for mask in loaded.road_edges),
                0,
            )
            self.assertEqual(snapshot.river_groups, loaded.copy_river_groups())
            self.assertEqual(snapshot.road_groups, loaded.copy_road_groups())
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
