"""尖顶六边形（odd-r 偏移坐标）的几何与邻接工具。

地图采用 pointy-top 六边形：
* 每一行内的六边形左右相邻，共享一条竖直边；
* 奇数行向右偏移半个六边形；
* 横向连续选择时，上边框自然形成 ``/\\/\\/\\`` 的折线。
"""

from __future__ import annotations

import math
from typing import Iterator

SQRT3 = math.sqrt(3.0)

# 方向编号固定为 0..5，后面道路描边也会使用同一套编号。
# 0=东，1=东南，2=西南，3=西，4=西北，5=东北
DIR_E = 0
DIR_SE = 1
DIR_SW = 2
DIR_W = 3
DIR_NW = 4
DIR_NE = 5

DIR_NAMES = ("东", "东南", "西南", "西", "西北", "东北")

# odd-r 偏移坐标的邻居。奇数行和偶数行不同。
NEIGHBORS_EVEN = (
    (1, 0),    # E
    (0, 1),    # SE
    (-1, 1),   # SW
    (-1, 0),   # W
    (-1, -1),  # NW
    (0, -1),   # NE
)
NEIGHBORS_ODD = (
    (1, 0),    # E
    (1, 1),    # SE
    (0, 1),    # SW
    (-1, 0),   # W
    (0, -1),   # NW
    (1, -1),   # NE
)

# 六边形的六个角，从正上方开始顺时针。
# 0=上，1=右上，2=右下，3=下，4=左下，5=左上。
CORNER_ANGLES = (-90.0, -30.0, 30.0, 90.0, 150.0, 210.0)

# 六条边第 i 条边连接角 i 与角 (i+1)%6。
# 边 index 与“跨过该边的邻居方向”一致。
EDGE_DIRS = (DIR_NE, DIR_E, DIR_SE, DIR_SW, DIR_W, DIR_NW)

# 对每一种邻居方向，共享边的编号。
EDGE_FOR_DIR = {d: i for i, d in enumerate(EDGE_DIRS)}


def neighbor_offset(direction: int, row: int) -> tuple[int, int]:
    """返回某一行在给定方向上的 (dc, dr)。"""
    return (NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN)[direction]


def neighbors(col: int, row: int, width: int, height: int) -> Iterator[tuple[int, int, int]]:
    """遍历有效邻居，返回 (dc, dr, direction)。"""
    table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
    for direction, (dc, dr) in enumerate(table):
        nc, nr = col + dc, row + dr
        if 0 <= nc < width and 0 <= nr < height:
            yield nc, nr, direction


def neighbor_indices(col: int, row: int, width: int, height: int) -> list[tuple[int, int, int]]:
    """返回 (flat_index, col, row) 的有效邻居。"""
    out: list[tuple[int, int, int]] = []
    base = row * width + col
    table = NEIGHBORS_ODD if (row & 1) else NEIGHBORS_EVEN
    for dc, dr in table:
        nc, nr = col + dc, row + dr
        if 0 <= nc < width and 0 <= nr < height:
            out.append((base + dr * width + dc, nc, nr))
    return out


def pixel_to_hex(x: float, y: float) -> tuple[int, int]:
    """把“以六边形外接圆半径为 1”的像素坐标转换为轴向坐标。

    该函数只负责连续坐标的取整；调用者需要再转为偏移坐标。
    """
    q = x / SQRT3 - y / 3.0
    r = (2.0 / 3.0) * y
    return axial_round(q, r)


def axial_round(q: float, r: float) -> tuple[int, int]:
    """立方坐标取整，返回 axial (q, r)。"""
    s = -q - r
    rq = round(q)
    rr = round(r)
    rs = round(s)
    dq = abs(rq - q)
    dr = abs(rr - r)
    ds = abs(rs - s)
    if dq > dr and dq > ds:
        rq = -rr - rs
    elif dr > ds:
        rr = -rq - rs
    return int(rq), int(rr)


def axial_to_offset(q: int, r: int) -> tuple[int, int]:
    """axial -> odd-r offset。"""
    return q + (r - (r & 1)) // 2, r


def offset_to_axial(col: int, row: int) -> tuple[int, int]:
    """odd-r offset -> axial。"""
    return col - (row - (row & 1)) // 2, row


def hex_center(col: int, row: int, size: float = 1.0) -> tuple[float, float]:
    """返回六边形中心坐标（pointy-top，odd-r）。"""
    return (
        SQRT3 * size * (col + 0.5 * (row & 1)),
        1.5 * size * row,
    )


def hex_corners(cx: float, cy: float, size: float = 1.0) -> list[tuple[float, float]]:
    """返回六边形的六个角，顺序与 CORNER_ANGLES 一致。"""
    return [
        (cx + size * math.cos(math.radians(a)), cy + size * math.sin(math.radians(a)))
        for a in CORNER_ANGLES
    ]


def hex_corner_offsets(size: float = 1.0) -> list[tuple[float, float]]:
    return [
        (size * math.cos(math.radians(a)), size * math.sin(math.radians(a)))
        for a in CORNER_ANGLES
    ]


def screen_to_hex(
    x: float,
    y: float,
    size: float,
    width: int,
    height: int,
) -> tuple[int, int] | None:
    """屏幕/世界坐标 -> 地图格坐标，越界返回 None。"""
    if size <= 0:
        return None
    q, r = pixel_to_hex(x / size, y / size)
    col, row = axial_to_offset(q, r)
    if 0 <= col < width and 0 <= row < height:
        return col, row
    return None


def world_bounds(width: int, height: int, size: float = 1.0) -> tuple[float, float, float, float]:
    """地图在给定六边形半径下的世界矩形：x, y, w, h（包含最外侧六边形的角）。"""
    if width <= 0 or height <= 0:
        return 0.0, 0.0, 0.0, 0.0
    half_w = SQRT3 * 0.5 * size
    top = -size
    bottom = 1.5 * size * (height - 1) + size
    left = -half_w
    right = SQRT3 * size * (width - 1 + 0.5 * ((height - 1) & 1)) + half_w
    return left, top, right - left, bottom - top


def hexes_in_radius(center_col: int, center_row: int, radius: int) -> Iterator[tuple[int, int, int]]:
    """遍历半径内的六边形（axial 圆），yield (col,row,ring)。"""
    cq, cr = offset_to_axial(center_col, center_row)
    for dq in range(-radius, radius + 1):
        lo = max(-radius, -dq - radius)
        hi = min(radius, -dq + radius)
        for dr in range(lo, hi + 1):
            col, row = axial_to_offset(cq + dq, cr + dr)
            ring = max(abs(dq), abs(dr), abs(-dq - dr))
            yield col, row, ring


def hex_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    aq, ar = offset_to_axial(*a)
    bq, br = offset_to_axial(*b)
    return max(abs(aq - bq), abs(ar - br), abs(-aq - ar + bq + br))


def hex_line(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    """返回两个六边形之间的连续格列表（含首尾）。

    使用 axial 坐标线性插值 + 立方取整，可保证拖动笔刷时不会跳过格子。
    """
    if a == b:
        return [a]
    aq, ar = offset_to_axial(*a)
    bq, br = offset_to_axial(*b)
    ad = -aq - ar
    bd = -bq - br
    n = max(abs(bq - aq), abs(br - ar), abs(bd - ad))
    result: list[tuple[int, int]] = []
    if n == 0:
        return [a]
    for i in range(n + 1):
        t = i / n
        q = aq + (bq - aq) * t
        r = ar + (br - ar) * t
        qr, rr = axial_round(q, r)
        cell = axial_to_offset(qr, rr)
        if not result or result[-1] != cell:
            result.append(cell)
    return result


def lerp_point(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
