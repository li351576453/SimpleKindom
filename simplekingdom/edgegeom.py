"""六边形边的几何工具。

河流现在直接由六边形的边组成。一条几何边由两个角点唯一确定；边可以
归属于它两侧任意一个六边形。绘制时先记录“鼠标所在侧”的候选六边形，
之后根据曲率圆圆心决定最终归属于哪一侧（内侧）。
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict

from .hexmath import (
    CORNER_ANGLES,
    EDGE_DIRS,
    EDGE_FOR_DIR,
    NEIGHBORS_EVEN,
    NEIGHBORS_ODD,
    SQRT3,
    hex_center,
    screen_to_hex,
)

# 与 model 中保持一致的整数角点坐标。
_CORNER_KEY_DATA = (
    (0, -2),
    (1, -1),
    (1, 1),
    (0, 2),
    (-1, 1),
    (-1, -1),
)

_CORNER_OFFSETS = [
    (math.cos(math.radians(a)), math.sin(math.radians(a))) for a in CORNER_ANGLES
]


def corner_key(cell: int, corner: int, width: int) -> tuple[int, int]:
    col, row = cell % width, cell // width
    base_x = 2 * col + (row & 1)
    base_y = 3 * row
    dx, dy = _CORNER_KEY_DATA[corner % 6]
    return base_x + dx, base_y + dy


def key_to_point(key: tuple[int, int]) -> tuple[float, float]:
    return key[0] * SQRT3 / 2.0, key[1] / 2.0


def edge_vertex_keys(cell: int, edge: int, width: int) -> tuple[tuple[int, int], tuple[int, int]]:
    return corner_key(cell, edge, width), corner_key(cell, (edge + 1) % 6, width)


def edge_geometry_key(
    cell: int,
    edge: int,
    width: int,
) -> tuple[tuple[int, int], tuple[int, int]]:
    a, b = edge_vertex_keys(cell, edge, width)
    return (a, b) if a <= b else (b, a)


def edge_endpoints_world(
    cell: int,
    edge: int,
    width: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    a, b = edge_vertex_keys(cell, edge, width)
    return key_to_point(a), key_to_point(b)


def edge_midpoint_world(cell: int, edge: int, width: int) -> tuple[float, float]:
    a, b = edge_endpoints_world(cell, edge, width)
    return (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0


def cell_center_world(cell: int, width: int) -> tuple[float, float]:
    return hex_center(cell % width, cell // width, 1.0)


def opposite_direction(direction: int) -> int:
    return (direction + 3) % 6


def adjacent_edge_choices(
    cell: int,
    edge: int,
    width: int,
    height: int,
) -> list[tuple[int, int]]:
    """返回同一条几何边两侧的 (cell, edge_index)，最多两个。"""
    choices = [(cell, edge)]
    col, row = cell % width, cell // width
    direction = EDGE_DIRS[edge]
    table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
    dc, dr = table[direction]
    nc, nr = col + dc, row + dr
    if 0 <= nc < width and 0 <= nr < height:
        neighbor = nr * width + nc
        neighbor_edge = EDGE_FOR_DIR[opposite_direction(direction)]
        # 防御性校验：两侧描述的必须是同一条几何边。
        if edge_geometry_key(cell, edge, width) == edge_geometry_key(
            neighbor, neighbor_edge, width
        ):
            choices.append((neighbor, neighbor_edge))
    return choices


def point_segment_distance(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    qx, qy = ax + dx * t, ay + dy * t
    return math.hypot(px - qx, py - qy)


def nearest_edge_of_cell(
    cell: int,
    px: float,
    py: float,
    width: int,
) -> tuple[int, float]:
    """给定格心坐标系的点，找到该格六条边中最近的一条。"""
    best_edge = 0
    best_distance = float("inf")
    for edge in range(6):
        (ax, ay), (bx, by) = edge_endpoints_world(cell, edge, width)
        distance = point_segment_distance(px, py, ax, ay, bx, by)
        if distance < best_distance:
            best_distance = distance
            best_edge = edge
    return best_edge, best_distance


def nearest_vertex_of_cell(
    cell: int,
    px: float,
    py: float,
    width: int,
) -> tuple[tuple[int, int], tuple[float, float]]:
    """返回该格六个角中离点最近的角点 key 及其世界坐标。"""
    best_key = corner_key(cell, 0, width)
    best_x, best_y = key_to_point(best_key)
    best_distance = (best_x - px) ** 2 + (best_y - py) ** 2
    for corner in range(1, 6):
        key = corner_key(cell, corner, width)
        x, y = key_to_point(key)
        distance = (x - px) ** 2 + (y - py) ** 2
        if distance < best_distance:
            best_key = key
            best_x, best_y = x, y
            best_distance = distance
    return best_key, (best_x, best_y)


# 六边形边在整数角点坐标中的六种方向向量。
_VERTEX_EDGE_DELTAS = (
    (1, 1),
    (0, 2),
    (-1, 1),
    (-1, -1),
    (0, -2),
    (1, -1),
)


def _edge_between_vertices(
    a: tuple[int, int],
    b: tuple[int, int],
    width: int,
    height: int,
) -> tuple[int, int] | None:
    """找到连接两个角点的六边形边，返回一个 owner/edge 候选。"""
    ax, ay = key_to_point(a)
    bx, by = key_to_point(b)
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return None
    nx, ny = -dy / length, dx / length
    target = a if a <= b else b
    other = b if target == a else a
    pair = (target, other)

    candidates: list[tuple[int, int]] = []
    for sign in (1.0, -1.0):
        cell = screen_to_hex(
            mx + nx * 0.02 * sign,
            my + ny * 0.02 * sign,
            1.0,
            width,
            height,
        )
        if cell is not None:
            candidates.append(cell)
    cell = screen_to_hex(mx, my, 1.0, width, height)
    if cell is not None:
        candidates.append(cell)

    seen: set[int] = set()
    for col, row in candidates:
        for dc, dr in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            nc, nr = col + dc, row + dr
            if not (0 <= nc < width and 0 <= nr < height):
                continue
            index = nr * width + nc
            if index in seen:
                continue
            seen.add(index)
            for edge in range(6):
                if edge_geometry_key(index, edge, width) == pair:
                    return index, edge
    return None


def vertex_path(
    start: tuple[int, int],
    end: tuple[int, int],
    width: int,
    height: int,
    *,
    max_nodes: int = 30000,
) -> list[tuple[int, int]] | None:
    """沿六边形边寻找两个角点之间的连续边链。

    路径长度按边数计算；找不到时返回 None。返回的每条边都首尾相接。
    """
    if start == end:
        return []

    cache: dict[tuple[tuple[int, int], tuple[int, int]], tuple[int, int] | None] = {}

    def neighbors(
        key: tuple[int, int],
    ) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        key_x, key_y = key
        result: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for dx, dy in _VERTEX_EDGE_DELTAS:
            nxt = (key_x + dx, key_y + dy)
            pair = (key, nxt) if key <= nxt else (nxt, key)
            if pair in cache:
                spec = cache[pair]
            else:
                spec = _edge_between_vertices(key, nxt, width, height)
                cache[pair] = spec
            if spec is not None:
                result.append((nxt, spec))
        return result

    ex, ey = key_to_point(end)

    def heuristic(key: tuple[int, int]) -> float:
        x, y = key_to_point(key)
        return math.hypot(x - ex, y - ey)

    counter = 0
    frontier: list[tuple[float, int, int, tuple[int, int]]] = [
        (heuristic(start), 0, counter, start)
    ]
    cost: dict[tuple[int, int], int] = {start: 0}
    came_from: dict[tuple[int, int], tuple[tuple[int, int], tuple[int, int]]] = {}
    visited = 0
    while frontier:
        _priority, steps, _tie, current = heapq.heappop(frontier)
        if steps != cost.get(current):
            continue
        if current == end:
            break
        visited += 1
        if visited > max_nodes:
            return None
        for nxt, spec in neighbors(current):
            next_cost = steps + 1
            if next_cost < cost.get(nxt, 1 << 30):
                cost[nxt] = next_cost
                came_from[nxt] = (current, spec)
                counter += 1
                heapq.heappush(
                    frontier,
                    (next_cost + heuristic(nxt), next_cost, counter, nxt),
                )
    if end not in came_from:
        return None
    edges: list[tuple[int, int]] = []
    current = end
    while current != start:
        previous, spec = came_from[current]
        edges.append(spec)
        current = previous
    edges.reverse()
    return edges


def cell_group_boundary_edges(
    cells: set[int],
    width: int,
    height: int,
) -> list[tuple[int, int, tuple[int, int], tuple[int, int]]]:
    """返回一组格子的完整边界边记录：(owner, edge, vertex_a, vertex_b)。"""
    records: list[tuple[int, int, tuple[int, int], tuple[int, int]]] = []
    for owner in cells:
        row, col = divmod(owner, width)
        table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
        for direction, (dc, dr) in enumerate(table):
            nc, nr = col + dc, row + dr
            if 0 <= nc < width and 0 <= nr < height and (nr * width + nc) in cells:
                continue
            edge = EDGE_DIRS.index(direction)
            a, b = edge_vertex_keys(owner, edge, width)
            records.append((owner, edge, a, b))
    return records


def trace_boundary_loops(
    records: list[tuple[int, int, tuple[int, int], tuple[int, int]]],
) -> list[list[int]]:
    """把边记录按共享端点串成闭合环，返回边记录下标环。"""
    node_edges: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, (_owner, _edge, a, b) in enumerate(records):
        node_edges[a].append(index)
        node_edges[b].append(index)

    used = bytearray(len(records))
    loops: list[list[int]] = []

    def other(rec_index: int, node: tuple[int, int]) -> tuple[int, int]:
        _owner, _edge, a, b = records[rec_index]
        return b if node == a else a

    for start in range(len(records)):
        if used[start]:
            continue
        rec = records[start]
        start_node = rec[2]
        current = rec[3]
        used[start] = 1
        loop = [start]
        guard = 0
        while current != start_node and guard < len(records) + 2:
            guard += 1
            candidates = [
                index for index in node_edges.get(current, ()) if not used[index]
            ]
            if not candidates:
                break
            nxt = candidates[0]
            used[nxt] = 1
            loop.append(nxt)
            current = other(nxt, current)
        if current == start_node and len(loop) >= 2:
            loops.append(loop)
    return loops


def _loop_vertices(
    records: list[tuple[int, int, tuple[int, int], tuple[int, int]]],
    loop: list[int],
) -> list[tuple[int, int]]:
    if not loop:
        return []
    first = records[loop[0]]
    vertices = [first[2]]
    for rec_index in loop[:-1]:
        _owner, _edge, a, b = records[rec_index]
        current = vertices[-1]
        vertices.append(b if current == a else a)
    return vertices


def cell_path_bank_specs(
    cells: list[int],
    width: int,
    height: int,
    *,
    upper: bool = True,
) -> list[tuple[int, int]]:
    """把一条格子路径转换为沿其一条外岸的连续边链。

    用于随机河流和旧版格子河流的迁移。返回按岸线顺序排列的
    ``(owner_cell, edge_index)``，owner 只是候选归属，后续会由曲率圆
    重新决定内侧归属。
    """
    if not cells:
        return []
    cell_set = set(cells)
    records = cell_group_boundary_edges(cell_set, width, height)
    loops = trace_boundary_loops(records)
    if not loops:
        return []
    loop = max(loops, key=len)
    vertices = _loop_vertices(records, loop)
    count = len(vertices)
    if count < 2:
        return []
    coords = [key_to_point(key) for key in vertices]

    endpoint_points = [
        cell_center_world(cells[0], width),
        cell_center_world(cells[-1], width),
    ]
    split_indices = [
        min(
            range(count),
            key=lambda i: (coords[i][0] - px) ** 2 + (coords[i][1] - py) ** 2,
        )
        for px, py in endpoint_points
    ]
    left, right = split_indices
    if left == right:
        right = max(
            range(count),
            key=lambda i: (coords[i][0] - coords[left][0]) ** 2
            + (coords[i][1] - coords[left][1]) ** 2,
        )
    if left == right:
        return []

    def arc(a: int, b: int) -> list[int]:
        if a < b:
            return list(range(a, b))
        return list(range(a, count)) + list(range(0, b))

    arc1 = arc(left, right)
    arc2 = arc(right, left)
    if not arc1:
        chosen = arc2
    elif not arc2:
        chosen = arc1
    else:
        def average_y(part: list[int]) -> float:
            return sum(
                (coords[i][1] + coords[(i + 1) % count][1]) / 2.0 for i in part
            ) / len(part)

        chosen = arc1 if (average_y(arc1) < average_y(arc2)) == upper else arc2

    specs: list[tuple[int, int]] = []
    for index in chosen:
        owner, edge, _a, _b = records[loop[index]]
        spec = (owner, edge)
        if not specs or specs[-1] != spec:
            specs.append(spec)
    return specs


def edge_depth(edges: list[tuple[int, int]], width: int) -> list[float]:
    """按边链顺序返回每条边到链首的累计距离，用于排序/调试。"""
    if not edges:
        return []
    points = [edge_midpoint_world(owner, edge, width) for owner, edge in edges]
    depths = [0.0]
    for a, b in zip(points, points[1:]):
        depths.append(depths[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    return depths
