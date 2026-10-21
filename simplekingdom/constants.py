"""地块、笔刷、覆盖层等全局常量。"""

from __future__ import annotations

from enum import IntEnum


class Terrain(IntEnum):
    OCEAN = 0
    LAKE = 1
    PLAINS = 2
    GRASSLAND = 3
    MOUNTAIN = 4
    DESERT = 5
    PLATEAU = 6


TERRAIN_ORDER = (
    Terrain.OCEAN,
    Terrain.LAKE,
    Terrain.PLAINS,
    Terrain.GRASSLAND,
    Terrain.MOUNTAIN,
    Terrain.DESERT,
    Terrain.PLATEAU,
)

TERRAIN_NAMES: dict[Terrain, str] = {
    Terrain.OCEAN: "海洋",
    Terrain.LAKE: "湖泊",
    Terrain.PLAINS: "平原",
    Terrain.GRASSLAND: "草地",
    Terrain.MOUNTAIN: "山地",
    Terrain.DESERT: "沙地",
    Terrain.PLATEAU: "高原",
}

TERRAIN_KEYS: dict[Terrain, str] = {
    Terrain.OCEAN: "1",
    Terrain.LAKE: "2",
    Terrain.PLAINS: "3",
    Terrain.GRASSLAND: "4",
    Terrain.MOUNTAIN: "5",
    Terrain.DESERT: "6",
    Terrain.PLATEAU: "7",
}

TERRAIN_COLORS: dict[Terrain, str] = {
    Terrain.OCEAN: "#28618f",
    Terrain.LAKE: "#79c9e6",
    Terrain.PLAINS: "#95cf72",
    Terrain.GRASSLAND: "#3b7253",
    Terrain.MOUNTAIN: "#204936",
    Terrain.DESERT: "#d9c26a",
    Terrain.PLATEAU: "#c8cec5",
}

TERRAIN_DARK_COLORS: dict[Terrain, str] = {
    Terrain.OCEAN: "#1d4d73",
    Terrain.LAKE: "#5eb3d4",
    Terrain.PLAINS: "#79b65b",
    Terrain.GRASSLAND: "#2c5a40",
    Terrain.MOUNTAIN: "#17392a",
    Terrain.DESERT: "#bfa64f",
    Terrain.PLATEAU: "#adb5a9",
}

TERRAIN_LIGHT_COLORS: dict[Terrain, str] = {
    Terrain.OCEAN: "#3476a8",
    Terrain.LAKE: "#93d9ee",
    Terrain.PLAINS: "#a9dd88",
    Terrain.GRASSLAND: "#4a8463",
    Terrain.MOUNTAIN: "#2e5d46",
    Terrain.DESERT: "#e7d180",
    Terrain.PLATEAU: "#dce1d8",
}

TERRAIN_DESCRIPTIONS: dict[Terrain, str] = {
    Terrain.OCEAN: "世界边缘与深海，默认地形",
    Terrain.LAKE: "内陆淡水，单块不超过 10 格",
    Terrain.PLAINS: "肥沃开阔，适合大面积铺展",
    Terrain.GRASSLAND: "温润草场，可零散或成片",
    Terrain.MOUNTAIN: "环绕高原的山脉与连绵山脊",
    Terrain.DESERT: "干旱沙地，常见于海岸边缘",
    Terrain.PLATEAU: "高海拔平缓台地，外围由山地环绕",
}

# 覆盖层按位保存，允许同一格同时有道路和河流（例如桥）。
OVERLAY_ROAD = 1
OVERLAY_RIVER = 2
OVERLAY_ALL = OVERLAY_ROAD | OVERLAY_RIVER

OVERLAY_NAMES = {
    OVERLAY_ROAD: "道路",
    OVERLAY_RIVER: "河流",
}

# 笔刷工具 ID
TOOL_TERRAIN = "terrain"
TOOL_ROAD = "road"
TOOL_RIVER = "river"
TOOL_ERASER = "eraser"

DEFAULT_MAP_SIZE = 500
CACHE_HEX_SIZE = 3.25
