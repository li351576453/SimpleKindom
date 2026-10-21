"""撤销 / 重做命令。"""

from __future__ import annotations

from PyQt6.QtGui import QUndoCommand

from .constants import OVERLAY_ALL
from .model import CellChange, MapModel, MapSnapshot


class CellStrokeCommand(QUndoCommand):
    """一次笔刷涂抹产生的局部修改。"""

    def __init__(
        self,
        model: MapModel,
        changes: list[CellChange],
        callback,
        text: str = "绘制",
        already_applied: bool = True,
        before_river_groups: tuple[tuple[tuple[int, int], ...], ...] | None = None,
        after_river_groups: tuple[tuple[tuple[int, int], ...], ...] | None = None,
        before_road_groups: tuple[tuple[tuple[int, int], ...], ...] | None = None,
        after_road_groups: tuple[tuple[tuple[int, int], ...], ...] | None = None,
    ) -> None:
        super().__init__(text)
        self.model = model
        self.changes = changes
        self.callback = callback
        self._first = already_applied
        self.before_river_groups = before_river_groups
        self.after_river_groups = after_river_groups
        self.before_road_groups = before_road_groups
        self.after_road_groups = after_road_groups
        self._has_groups = (
            before_river_groups is not None
            and after_river_groups is not None
            and before_river_groups != after_river_groups
        )
        self._has_road_groups = (
            before_road_groups is not None
            and after_road_groups is not None
            and before_road_groups != after_road_groups
        )
        self._has_overlay = any(
            c.old_overlay != c.new_overlay for c in changes
        )
        self.cells = [c.index for c in changes]

    def redo(self) -> None:
        if self._first:
            self._first = False
            self.callback(self, False)
            return
        for c in self.changes:
            self.model.terrain[c.index] = c.new_terrain
            self.model.overlay[c.index] = c.new_overlay & OVERLAY_ALL
        if self._has_groups:
            self.model.set_river_groups(self.after_river_groups or ())
        if self._has_road_groups:
            self.model.set_road_groups(self.after_road_groups or ())
        if self._has_overlay or self._has_groups or self._has_road_groups:
            self.model.rebuild_all_edges()
        self.model.touch()
        self.callback(self, False)

    def undo(self) -> None:
        for c in self.changes:
            self.model.terrain[c.index] = c.old_terrain
            self.model.overlay[c.index] = c.old_overlay & OVERLAY_ALL
        if self._has_groups:
            self.model.set_river_groups(self.before_river_groups or ())
        if self._has_road_groups:
            self.model.set_road_groups(self.before_road_groups or ())
        if self._has_overlay or self._has_groups or self._has_road_groups:
            self.model.rebuild_all_edges()
        self.model.touch()
        self.callback(self, False)


class WholeMapCommand(QUndoCommand):
    """随机生成、清空、新建等整图替换。"""

    def __init__(
        self,
        model: MapModel,
        before: MapSnapshot,
        after: MapSnapshot,
        before_meta: tuple[int, str],
        after_meta: tuple[int, str],
        callback,
        text: str = "替换地图",
        already_applied: bool = True,
    ) -> None:
        super().__init__(text)
        self.model = model
        self.before = before
        self.after = after
        self.before_meta = before_meta
        self.after_meta = after_meta
        self.callback = callback
        self._first = already_applied
        self.cells = []

    def redo(self) -> None:
        if self._first:
            self._first = False
            self.callback(self, True)
            return
        self.model.restore(self.after)
        self.model.seed, self.model.name = self.after_meta
        self.callback(self, True)

    def undo(self) -> None:
        self.model.restore(self.before)
        self.model.seed, self.model.name = self.before_meta
        self.callback(self, True)
