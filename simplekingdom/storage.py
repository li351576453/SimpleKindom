"""地图存档格式（压缩二进制）。"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from .constants import OVERLAY_RIVER
from .edgegeom import cell_path_bank_specs
from .model import MapModel, MapSnapshot

MAGIC = b"SKMAP01\n"
VERSION = 4
HEADER = struct.Struct(">8sHHHQHI")  # magic, version, width, height, seed, name_len, payload_len


class MapFormatError(Exception):
    pass


def _encode_river_groups(groups) -> bytes:
    payload = bytearray(struct.pack(">I", len(groups)))
    for group in groups:
        edges = sorted(set(group))
        payload += struct.pack(">I", len(edges))
        for owner, edge in edges:
            payload += struct.pack(">II", int(owner), int(edge))
    return bytes(payload)


def _decode_river_groups(
    data: bytes,
    offset: int,
    cell_count: int,
) -> tuple[list[list[tuple[int, int]]], int]:
    if offset + 4 > len(data):
        raise MapFormatError("河流分组数据不完整")
    (group_count,) = struct.unpack_from(">I", data, offset)
    offset += 4
    groups: list[list[tuple[int, int]]] = []
    for _ in range(group_count):
        if offset + 4 > len(data):
            raise MapFormatError("河流分组数据不完整")
        (edge_count,) = struct.unpack_from(">I", data, offset)
        offset += 4
        byte_count = edge_count * 8
        if offset + byte_count > len(data):
            raise MapFormatError("河流分组数据不完整")
        group: list[tuple[int, int]] = []
        for _edge in range(edge_count):
            owner, edge = struct.unpack_from(">II", data, offset)
            offset += 8
            if owner >= cell_count or edge >= 6:
                raise MapFormatError("河流边数据不合法")
            group.append((int(owner), int(edge)))
        groups.append(group)
    return groups, offset


def _decode_legacy_cell_groups(
    data: bytes,
    offset: int,
    cell_count: int,
) -> tuple[list[list[int]], int]:
    """读取旧版 version 2 的格子分组。"""
    if offset + 4 > len(data):
        raise MapFormatError("旧版河流分组数据不完整")
    (group_count,) = struct.unpack_from(">I", data, offset)
    offset += 4
    groups: list[list[int]] = []
    for _ in range(group_count):
        if offset + 4 > len(data):
            raise MapFormatError("旧版河流分组数据不完整")
        (cell_count_in_group,) = struct.unpack_from(">I", data, offset)
        offset += 4
        if cell_count_in_group > cell_count:
            raise MapFormatError("旧版河流分组成员数量不合法")
        byte_count = cell_count_in_group * 4
        if offset + byte_count > len(data):
            raise MapFormatError("旧版河流分组数据不完整")
        if cell_count_in_group:
            cells = list(
                struct.unpack_from(f">{cell_count_in_group}I", data, offset)
            )
            if any(cell >= cell_count for cell in cells):
                raise MapFormatError("旧版河流分组包含越界格")
            groups.append([int(cell) for cell in cells])
        else:
            groups.append([])
        offset += byte_count
    return groups, offset


def save_map(model: MapModel, path: str | Path) -> None:
    data = (
        bytes(model.terrain)
        + bytes(model.overlay)
        + _encode_river_groups(model.copy_river_groups())
        + _encode_river_groups(model.copy_road_groups())
    )
    packed = zlib.compress(data, level=6)
    name = model.name.encode("utf-8")[:240]
    header = HEADER.pack(
        MAGIC,
        VERSION,
        model.width,
        model.height,
        int(model.seed) & 0xFFFFFFFFFFFFFFFF,
        len(name),
        len(packed),
    )
    Path(path).write_bytes(header + name + packed)


def load_map(path: str | Path) -> tuple[MapModel, MapSnapshot]:
    raw = Path(path).read_bytes()
    if len(raw) < HEADER.size:
        raise MapFormatError("文件过短，不是有效的地图存档")
    magic, version, width, height, seed, name_len, payload_len = HEADER.unpack_from(raw)
    if magic != MAGIC:
        raise MapFormatError("文件格式不正确")
    if version not in (1, 2, 3, VERSION):
        raise MapFormatError(f"不支持的存档版本：{version}")
    if width <= 0 or height <= 0 or width > 4000 or height > 4000:
        raise MapFormatError("地图尺寸不合法")
    offset = HEADER.size
    name_bytes = raw[offset : offset + name_len]
    offset += name_len
    payload = raw[offset : offset + payload_len]
    if len(payload) != payload_len:
        raise MapFormatError("存档数据不完整")
    try:
        decoded = zlib.decompress(payload)
    except zlib.error as exc:
        raise MapFormatError("存档解压失败") from exc
    expected = width * height * 2
    if len(decoded) < expected:
        raise MapFormatError("地块数据尺寸不匹配")
    split = width * height
    terrain = decoded[:split]
    overlay = decoded[split:expected]
    river_groups: list[list[tuple[int, int]]] = []
    road_groups: list[list[tuple[int, int]]] = []
    legacy_cell_groups: list[list[int]] = []
    if version >= 3:
        river_groups, end_offset = _decode_river_groups(
            decoded, expected, width * height
        )
        if version >= 4:
            road_groups, end_offset = _decode_river_groups(
                decoded, end_offset, width * height
            )
        if end_offset != len(decoded):
            raise MapFormatError("存档末尾存在无法识别的数据")
    elif version == 2:
        legacy_cell_groups, end_offset = _decode_legacy_cell_groups(
            decoded, expected, width * height
        )
        if end_offset != len(decoded):
            raise MapFormatError("存档末尾存在无法识别的数据")
    elif len(decoded) != expected:
        raise MapFormatError("地块数据尺寸不匹配")

    model = MapModel(width, height)
    model.seed = int(seed)
    model.name = name_bytes.decode("utf-8", errors="replace") or "未命名大陆"
    if version >= 4:
        model.set_arrays(
            terrain,
            overlay,
            river_groups=river_groups,
            road_groups=road_groups,
        )
    elif version == 3:
        model.set_arrays(terrain, overlay, river_groups=river_groups)
    elif version == 2 and legacy_cell_groups:
        clean_overlay = bytearray(overlay)
        for index in range(len(clean_overlay)):
            clean_overlay[index] &= 0xFF ^ OVERLAY_RIVER
        model.set_arrays(terrain, bytes(clean_overlay))
        for cell_group in legacy_cell_groups:
            specs = cell_path_bank_specs(
                sorted(cell_group), width, height, upper=True
            )
            if specs:
                model.add_river_edge_group(specs)
        model.rebuild_all_edges()
    else:
        # version 1 或没有旧分组信息的 version 2：从格子覆盖层自动转边链。
        model.set_arrays(terrain, overlay)
    model.revision = 0
    snapshot = model.snapshot()
    return model, snapshot
