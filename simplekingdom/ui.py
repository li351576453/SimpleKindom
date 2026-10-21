"""SimpleKingdom 地图编辑器主界面。"""

from __future__ import annotations

import random
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QFont,
    QIntValidator,
    QKeySequence,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .canvas import MapCanvas
from .commands import WholeMapCommand
from .constants import (
    DEFAULT_MAP_SIZE,
    TERRAIN_COLORS,
    TERRAIN_DESCRIPTIONS,
    TERRAIN_KEYS,
    TERRAIN_NAMES,
    TERRAIN_ORDER,
    TOOL_ERASER,
    TOOL_RIVER,
    TOOL_ROAD,
    TOOL_TERRAIN,
    Terrain,
)
from .generator import GenerationResult, TerrainGenerator
from .model import MapModel
from .render import render_overview
from .storage import MapFormatError, load_map, save_map
from .widgets import (
    LogoWidget,
    Minimap,
    StatCard,
    Toast,
    make_app_icon,
    make_color_icon,
    make_icon,
)


class GenerationWorker(QThread):
    progressed = pyqtSignal(int, str)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, params: dict, parent=None) -> None:
        super().__init__(parent)
        self.params = params

    def run(self) -> None:
        try:
            gen = TerrainGenerator(
                **self.params,
                progress=lambda p, s: self.progressed.emit(p, s),
            )
            result = gen.generate()
            self.succeeded.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MapEditorWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SimpleKingdom · 地图工坊")
        self.setWindowIcon(make_app_icon(48))
        self.resize(1460, 930)
        self.setMinimumSize(1180, 760)

        self.model = MapModel(DEFAULT_MAP_SIZE, DEFAULT_MAP_SIZE)
        from PyQt6.QtGui import QUndoStack

        self.undo_stack = QUndoStack(self)
        self._extra_dirty = False
        self._current_file: str | None = None
        self._gen_worker: GenerationWorker | None = None
        self._gen_dialog: QProgressDialog | None = None
        self._slider_sync = False

        self.canvas = MapCanvas(self.model, self.undo_stack, self)
        self.minimap = Minimap(self.model)
        self.toast = Toast(self)
        self._build_ui()
        self._bind_shortcuts()
        self._connect_signals()
        self._sync_all_views(initial=True)

    # ------------------------------------------------------------------ 样式
    def _separator(self, vertical: bool = False) -> QFrame:
        line = QFrame()
        line.setObjectName("VSeparator" if vertical else "Separator")
        if vertical:
            line.setFixedWidth(1)
            line.setFixedHeight(30)
        else:
            line.setFixedHeight(1)
        return line

    def _label(self, text: str, name: str = "") -> QLabel:
        label = QLabel(text)
        if name:
            label.setObjectName(name)
        return label

    def _section(self, text: str) -> QLabel:
        return self._label(text, "SectionLabel")

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_left_panel())
        workspace = QFrame()
        workspace.setObjectName("Workspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(12, 12, 12, 12)
        workspace_layout.addWidget(self.canvas)
        body.addWidget(workspace, 1)
        body.addWidget(self._build_right_panel())
        root.addLayout(body, 1)
        root.addWidget(self._build_statusbar())
        self.setCentralWidget(central)
        self.toast.setParent(central)
        self.toast.raise_()

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(70)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 9, 18, 9)
        layout.setSpacing(12)

        layout.addWidget(LogoWidget(header))
        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.setContentsMargins(0, 1, 0, 0)
        top = QLabel("SIMPLE KINGDOM")
        top.setObjectName("BrandTop")
        f = top.font()
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.7)
        top.setFont(f)
        bottom = QLabel("地图工坊")
        bottom.setObjectName("BrandBottom")
        brand.addWidget(top)
        brand.addWidget(bottom)
        layout.addLayout(brand)
        layout.addSpacing(8)
        layout.addWidget(self._separator(vertical=True))

        doc = QVBoxLayout()
        doc.setSpacing(1)
        doc.setContentsMargins(0, 2, 0, 0)
        self.doc_name = QLabel("未命名大陆")
        self.doc_name.setObjectName("DocName")
        self.doc_meta = QLabel("500 × 500  ·  六边形世界")
        self.doc_meta.setObjectName("DocMeta")
        doc.addWidget(self.doc_name)
        doc.addWidget(self.doc_meta)
        layout.addLayout(doc)
        layout.addStretch(1)

        self.btn_new = self._header_button("新建地图 (Ctrl+N)", "new", self.new_map)
        self.btn_open = self._header_button("打开地图 (Ctrl+O)", "open", self.open_map)
        self.btn_save = self._header_button("保存地图 (Ctrl+S)", "save", self.save_map)
        self.btn_export = self._header_button("导出 PNG", "export", self.export_png)
        for b in (self.btn_new, self.btn_open, self.btn_save, self.btn_export):
            layout.addWidget(b)
        layout.addWidget(self._separator(vertical=True))
        self.btn_undo = self._icon_button("撤销 (Ctrl+Z)", "undo", self.undo)
        self.btn_redo = self._icon_button("重做 (Ctrl+Y)", "redo", self.redo)
        self.btn_fit = self._icon_button("适应窗口 (Ctrl+0)", "fit", self.canvas.fit_to_view)
        layout.addWidget(self.btn_undo)
        layout.addWidget(self.btn_redo)
        layout.addWidget(self.btn_fit)
        layout.addSpacing(4)
        self.btn_generate = QToolButton(header)
        self.btn_generate.setObjectName("GenerateButton")
        self.btn_generate.setText("随机生成")
        self.btn_generate.setIcon(make_icon("spark", "#1b231a", 17))
        self.btn_generate.setIconSize(QSize(17, 17))
        self.btn_generate.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_generate.setToolTip("随机生成一片大陆 (Ctrl+G)")
        self.btn_generate.clicked.connect(self.open_generator)
        layout.addWidget(self.btn_generate)
        return header

    def _header_button(self, tooltip: str, icon: str, callback) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("HeaderButton")
        button.setIcon(make_icon(icon, "#dfd7c6", 18))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tooltip)
        button.setFixedSize(36, 34)
        button.clicked.connect(callback)
        return button

    def _icon_button(self, tooltip: str, icon: str, callback) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("IconButton")
        button.setIcon(make_icon(icon, "#d6cebd", 19))
        button.setIconSize(QSize(19, 19))
        button.setToolTip(tooltip)
        button.setFixedSize(34, 34)
        button.clicked.connect(callback)
        return button

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("PanelEdgeLeft")
        panel.setFixedWidth(264)
        root = QVBoxLayout(panel)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(10)

        title = self._label("绘制工具", "PanelTitle")
        subtitle = self._label("TERRAIN & PATH BRUSH", "PanelSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(self._separator())

        header = QHBoxLayout()
        header.addWidget(self._section("地块笔刷"))
        header.addStretch(1)
        header.addWidget(self._label("快捷键 1–7", "Hint"))
        root.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(7)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_buttons: dict[int, QPushButton] = {}
        for i, terrain in enumerate(TERRAIN_ORDER):
            btn = QPushButton(TERRAIN_NAMES[terrain])
            btn.setObjectName("TerrainButton")
            btn.setCheckable(True)
            btn.setFixedHeight(45)
            btn.setIcon(make_color_icon(TERRAIN_COLORS[terrain], 24))
            btn.setIconSize(QSize(20, 20))
            btn.setToolTip(
                f"{TERRAIN_NAMES[terrain]}  [{TERRAIN_KEYS[terrain]}]\n{TERRAIN_DESCRIPTIONS[terrain]}"
            )
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.tool_group.addButton(btn, int(terrain))
            self.tool_buttons[int(terrain)] = btn
            grid.addWidget(btn, i // 2, i % 2)
        root.addLayout(grid)

        header2 = QHBoxLayout()
        header2.addWidget(self._section("路径与修整"))
        header2.addStretch(1)
        header2.addWidget(self._label("8 · 9 · E", "Hint"))
        root.addLayout(header2)
        self.btn_road = self._overlay_button("道路", "road", "#c08048")
        self.btn_river = self._overlay_button("河流", "river", "#8bd8ef")
        self.btn_eraser = self._overlay_button("橡皮擦", "eraser", "#ff9a84")
        self.btn_road.setToolTip(
            "道路 [8]\n路径点或逐边编辑；每条笔触是独立道路；右键擦边"
        )
        self.btn_river.setToolTip(
            "河流 [9]\n路径点或逐边编辑；每条笔触是独立河道；右键擦边"
        )
        self.btn_eraser.setToolTip(
            "橡皮擦 [E]\n按笔刷范围清除地块、河流边与道路边"
        )
        self.tool_group.addButton(self.btn_road, 100)
        self.tool_group.addButton(self.btn_river, 101)
        self.tool_group.addButton(self.btn_eraser, 102)
        root.addWidget(self.btn_road)
        root.addWidget(self.btn_river)
        root.addWidget(self.btn_eraser)
        self.path_mode_check = QCheckBox("道路 / 河流路径点连线")
        self.path_mode_check.setToolTip(
            "开启后：左键放置路径点（自动吸附六边形顶点），程序沿边自动连线；"
            "双击/Enter 完成，右键/Backspace 撤点，Esc 取消"
        )
        self.path_mode_check.setChecked(True)
        self.path_mode_check.toggled.connect(self._on_path_mode_toggled)
        root.addWidget(self.path_mode_check)

        root.addWidget(self._separator())
        brush_row = QHBoxLayout()
        brush_row.addWidget(self._section("笔刷大小"))
        brush_row.addStretch(1)
        self.brush_value = self._label("1 圈 · 1 格", "ValueLabel")
        brush_row.addWidget(self.brush_value)
        root.addLayout(brush_row)
        slider_row = QHBoxLayout()
        self.brush_slider = QSlider(Qt.Orientation.Horizontal)
        self.brush_slider.setRange(1, 10)
        self.brush_slider.setValue(1)
        self.brush_spin = QSpinBox()
        self.brush_spin.setRange(1, 10)
        self.brush_spin.setValue(1)
        self.brush_spin.setFixedWidth(54)
        slider_row.addWidget(self.brush_slider, 1)
        slider_row.addWidget(self.brush_spin)
        root.addLayout(slider_row)
        brush_hint = self._label(
            "半径越大，一次覆盖的六边形越多；道路/河流可勾选上方路径点模式。",
            "Hint",
        )
        brush_hint.setWordWrap(True)
        brush_hint.setMinimumHeight(30)
        root.addWidget(brush_hint)

        hint_card = QFrame()
        hint_card.setObjectName("Card")
        hc = QVBoxLayout(hint_card)
        hc.setContentsMargins(12, 10, 12, 10)
        hc.setSpacing(4)
        hc.addWidget(self._label("绘制提示", "ValueLabel"))
        tip = self._label(
            "左键绘制 · 右键擦边 · 空格拖动 · 滚轮缩放",
            "Hint",
        )
        tip.setWordWrap(True)
        hc.addWidget(tip)
        edge_tip = self._label(
            "道路/河流可勾选路径点连线：左键加点，双击/Enter 完成。",
            "Hint",
        )
        edge_tip.setWordWrap(True)
        hc.addWidget(edge_tip)
        root.addWidget(hint_card)
        root.addStretch(1)
        foot = self._label("SIMPLEKINGDOM · MAP FORGE v0.1", "Hint")
        foot.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(foot)

        self.tool_group.idClicked.connect(self._on_tool_id)
        self.tool_buttons[int(Terrain.PLAINS)].setChecked(True)
        return panel

    def _overlay_button(self, name: str, icon: str, color: str) -> QPushButton:
        btn = QPushButton(name)
        btn.setObjectName("OverlayButton")
        btn.setCheckable(True)
        btn.setFixedHeight(38)
        btn.setIcon(make_icon(icon, color, 20))
        btn.setIconSize(QSize(18, 18))
        return btn

    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("PanelEdgeRight")
        panel.setFixedWidth(326)

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(panel)
        scroll.setObjectName("RightScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background-color:#101920;")
        content = QWidget()
        content.setObjectName("RightContent")
        root = QVBoxLayout(content)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(11)

        root.addWidget(self._label("世界概览", "PanelTitle"))
        root.addWidget(self._label("WORLD OVERVIEW", "PanelSubtitle"))
        root.addWidget(self._separator())

        name_row = QHBoxLayout()
        name_row.setSpacing(7)
        self.name_edit = QLineEdit()
        self.name_edit.setText(self.model.name)
        self.name_edit.setPlaceholderText("给这片大陆起个名字")
        self.name_edit.setMaxLength(40)
        self.name_edit.setToolTip("地图名称")
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        map_card = QFrame()
        map_card.setObjectName("Card")
        mc = QVBoxLayout(map_card)
        mc.setContentsMargins(10, 10, 10, 10)
        mc.setSpacing(7)
        map_head = QHBoxLayout()
        map_head.addWidget(self._label("地图预览", "ValueLabel"))
        map_head.addStretch(1)
        map_head.addWidget(self._label("点击跳转", "Hint"))
        mc.addLayout(map_head)
        self.minimap.setMinimumHeight(196)
        self.minimap.setMaximumHeight(215)
        mc.addWidget(self.minimap)
        root.addWidget(map_card)

        stats = QGridLayout()
        stats.setHorizontalSpacing(8)
        stats.setVerticalSpacing(8)
        self.stat_land = StatCard("陆地面积", "#85c47a")
        self.stat_lake = StatCard("湖泊", "#79c9e6")
        self.stat_river = StatCard("河流", "#63b4d6")
        self.stat_road = StatCard("道路", "#d8c58e")
        stats.addWidget(self.stat_land, 0, 0)
        stats.addWidget(self.stat_lake, 0, 1)
        stats.addWidget(self.stat_river, 1, 0)
        stats.addWidget(self.stat_road, 1, 1)
        root.addLayout(stats)

        gen_card = QFrame()
        gen_card.setObjectName("Card")
        gc = QVBoxLayout(gen_card)
        gc.setContentsMargins(13, 12, 13, 13)
        gc.setSpacing(8)
        gen_head = QHBoxLayout()
        gen_head.addWidget(self._label("随机生成大陆", "ValueLabel"))
        gen_head.addStretch(1)
        gc.addLayout(gen_head)
        seed_row = QHBoxLayout()
        seed_label = self._label("种子", "Hint")
        seed_label.setFixedWidth(30)
        self.seed_edit = QLineEdit(str(self.model.seed))
        self.seed_edit.setObjectName("SeedInput")
        self.seed_edit.setValidator(QIntValidator(1, 2_000_000_000, self))
        self.seed_edit.setToolTip("相同种子 + 相同参数会生成相同地图")
        seed_row.addWidget(seed_label)
        seed_row.addWidget(self.seed_edit, 1)
        self.dice_btn = QToolButton()
        self.dice_btn.setObjectName("IconButton")
        self.dice_btn.setText("⟳")
        self.dice_btn.setToolTip("随机种子")
        self.dice_btn.setFixedSize(30, 28)
        self.dice_btn.clicked.connect(self._randomize_seed)
        seed_row.addWidget(self.dice_btn)
        gc.addLayout(seed_row)

        self.sliders: dict[str, tuple[QSlider, QLabel]] = {}
        gc.addLayout(self._slider_row("陆地规模", "land", 20, 48, 34, "%"))
        gc.addLayout(self._slider_row("岛屿数量", "islands", 0, 100, 55, "%"))
        gc.addLayout(self._slider_row("湖泊密度", "lakes", 0, 100, 55, "%"))
        gc.addLayout(self._slider_row("河流数量", "rivers", 0, 100, 58, "%"))

        self.btn_generate_panel = QToolButton()
        self.btn_generate_panel.setObjectName("GenerateButton")
        self.btn_generate_panel.setText("生成新大陆")
        self.btn_generate_panel.setIcon(make_icon("spark", "#1b231a", 16))
        self.btn_generate_panel.setIconSize(QSize(16, 16))
        self.btn_generate_panel.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_generate_panel.setFixedHeight(36)
        self.btn_generate_panel.setStyleSheet(
            "QToolButton { background-color:#d8b45a; border:1px solid #e5c777;"
            " border-radius:8px; color:#172019; padding:6px 13px; font-weight:700; }"
            "QToolButton:hover { background-color:#e6c66f; }"
            "QToolButton:pressed { background-color:#c5a24a; }"
        )
        self.btn_generate_panel.clicked.connect(self.open_generator)
        gc.addWidget(self.btn_generate_panel)
        gc.addWidget(
            self._label(
                "主大陆保持完整，外围生成零碎小岛。道路不会自然生成。",
                "Hint",
            )
        )
        root.addWidget(gen_card)
        root.addStretch(1)
        foot = self._label("地形生成器 · 六边形世界 500 × 500", "Hint")
        foot.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(foot)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return panel

    def _slider_row(
        self,
        title: str,
        key: str,
        minimum: int,
        maximum: int,
        value: int,
        suffix: str,
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(7)
        label = self._label(title, "Hint")
        label.setFixedWidth(58)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        value_label = self._label(f"{value}{suffix}", "ValueLabel")
        value_label.setFixedWidth(34)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider.valueChanged.connect(
            lambda v, lbl=value_label, suf=suffix: lbl.setText(f"{v}{suf}")
        )
        row.addWidget(label)
        row.addWidget(slider, 1)
        row.addWidget(value_label)
        self.sliders[key] = (slider, value_label)
        return row

    def _build_statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(31)
        bar.setStyleSheet(
            "QFrame#StatusBar { background:#0d161d; border-top:1px solid #1f2d36; }"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(10)
        accent = self._label("◆", "StatusAccent")
        self.status_hint = self._label("工具：平原  ·  笔刷 1 圈（1 格）", "StatusText")
        layout.addWidget(accent)
        layout.addWidget(self.status_hint)
        layout.addStretch(1)
        self.cursor_label = self._label("(—, —)  海洋", "StatusText")
        self.cursor_label.setMinimumWidth(160)
        self.zoom_label = self._label("100%", "StatusText")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.cursor_label)
        layout.addWidget(self._label("│", "StatusDivider"))
        layout.addWidget(self._label("500 × 500", "StatusText"))
        layout.addWidget(self._label("│", "StatusDivider"))
        self.brush_status = self._label("笔刷 1", "StatusText")
        layout.addWidget(self.brush_status)
        layout.addWidget(self._label("│", "StatusDivider"))
        layout.addWidget(self.zoom_label)
        return bar

    # ------------------------------------------------------------------ 连接
    def _connect_signals(self) -> None:
        self.canvas.cursor_info.connect(self.cursor_label.setText)
        self.canvas.view_changed.connect(self.minimap.set_view_rect)
        self.canvas.zoom_changed.connect(lambda p: self.zoom_label.setText(f"{p}%"))
        self.canvas.map_edited.connect(self._on_map_edited)
        self.canvas.path_changed.connect(self._on_path_changed)
        self.canvas.set_path_mode(self.path_mode_check.isChecked())
        self.minimap.navigate.connect(self.canvas.center_on_world)
        self.brush_slider.valueChanged.connect(self._on_brush_slider)
        self.brush_spin.valueChanged.connect(self._on_brush_spin)
        self.name_edit.editingFinished.connect(self._on_name_edited)
        self.undo_stack.canUndoChanged.connect(self.btn_undo.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.btn_redo.setEnabled)
        self.undo_stack.cleanChanged.connect(self._on_clean_changed)
        self.undo_stack.indexChanged.connect(self._update_undo_buttons)
        self._update_undo_buttons()

    def _bind_shortcuts(self) -> None:
        def add(seq: str, callback) -> None:
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)

        add("Ctrl+N", self.new_map)
        add("Ctrl+O", self.open_map)
        add("Ctrl+S", self.save_map)
        add("Ctrl+Shift+S", self.save_map_as)
        add("Ctrl+E", self.export_png)
        add("Ctrl+Z", lambda: self._shortcut_tool(self.undo))
        add("Ctrl+Y", lambda: self._shortcut_tool(self.redo))
        add("Ctrl+Shift+Z", lambda: self._shortcut_tool(self.redo))
        add("Ctrl+G", self.open_generator)
        add("Ctrl+0", self.canvas.fit_to_view)
        fit_shortcut = QShortcut(QKeySequence("F"), self)
        fit_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        fit_shortcut.activated.connect(
            lambda: self._shortcut_tool(self.canvas.fit_to_view)
        )
        for i, terrain in enumerate(TERRAIN_ORDER):
            shortcut = QShortcut(QKeySequence(str(i + 1)), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(
                lambda t=terrain: self._shortcut_tool(lambda: self._activate_tool(int(t)))
            )
        for seq, tool_id in (("8", 100), ("9", 101), ("E", 102), ("0", 102)):
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(
                lambda tid=tool_id: self._shortcut_tool(lambda: self._activate_tool(tid))
            )
        for seq, delta in (("[", -1), ("]", 1)):
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(
                lambda d=delta: self._shortcut_tool(lambda: self._nudge_brush(d))
            )

    def _shortcut_tool(self, callback) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QSpinBox)):
            return
        callback()

    def _nudge_brush(self, delta: int) -> None:
        value = max(1, min(10, self.brush_slider.value() + delta))
        self.brush_slider.setValue(value)

    # ------------------------------------------------------------------ 工具
    def _on_tool_id(self, tool_id: int) -> None:
        self._activate_tool(tool_id)

    def _activate_tool(self, tool_id: int) -> None:
        button = self.tool_buttons.get(tool_id)
        if button is None:
            if tool_id == 100:
                button = self.btn_road
            elif tool_id == 101:
                button = self.btn_river
            elif tool_id == 102:
                button = self.btn_eraser
        if button is not None:
            button.setChecked(True)
        if tool_id in (100, 101, 102):
            if tool_id == 100:
                self.canvas.set_tool(TOOL_ROAD)
                self.brush_slider.setVisible(False)
                self.brush_spin.setVisible(False)
                self.brush_slider.setEnabled(False)
                self.brush_spin.setEnabled(False)
                self._refresh_path_status()
            elif tool_id == 101:
                self.canvas.set_tool(TOOL_RIVER)
                self.brush_slider.setVisible(False)
                self.brush_spin.setVisible(False)
                self.brush_slider.setEnabled(False)
                self.brush_spin.setEnabled(False)
                self._refresh_path_status()
            else:
                self.canvas.set_tool(TOOL_ERASER)
                self.brush_slider.setVisible(True)
                self.brush_spin.setVisible(True)
                self.brush_slider.setEnabled(True)
                self.brush_spin.setEnabled(True)
                self.brush_value.setText(
                    f"{self.brush_slider.value()} 圈 · {self._brush_count()} 格"
                )
                self.brush_status.setText(f"笔刷 {self.brush_slider.value()}")
                self.status_hint.setText(
                    "工具：橡皮擦  ·  清除地块、河流边与道路边"
                )
        else:
            terrain = Terrain(tool_id)
            self.canvas.set_tool(TOOL_TERRAIN, terrain)
            self.brush_slider.setVisible(True)
            self.brush_spin.setVisible(True)
            self.brush_slider.setEnabled(True)
            self.brush_spin.setEnabled(True)
            self.brush_value.setText(
                f"{self.brush_slider.value()} 圈 · {self._brush_count()} 格"
            )
            self.brush_status.setText(f"笔刷 {self.brush_slider.value()}")
            self.status_hint.setText(
                f"工具：{TERRAIN_NAMES[terrain]}  ·  笔刷 {self.brush_slider.value()} 圈"
                f"（{self._brush_count()} 格）"
            )

    def _on_brush_slider(self, value: int) -> None:
        if self._slider_sync:
            return
        self._slider_sync = True
        self.brush_spin.setValue(value)
        self._slider_sync = False
        self._set_brush(value)

    def _on_brush_spin(self, value: int) -> None:
        if self._slider_sync:
            return
        self._slider_sync = True
        self.brush_slider.setValue(value)
        self._slider_sync = False
        self._set_brush(value)

    def _set_brush(self, value: int) -> None:
        self.canvas.set_brush_size(value)
        if self.canvas.tool in (TOOL_ROAD, TOOL_RIVER):
            self._refresh_path_status()
            return
        self.brush_value.setText(f"{value} 圈 · {self._brush_count()} 格")
        self.brush_status.setText(f"笔刷 {value}")
        if self.canvas.tool == TOOL_TERRAIN:
            self.status_hint.setText(
                f"工具：{TERRAIN_NAMES[self.canvas.selected_terrain]}  ·  "
                f"笔刷 {value} 圈（{self._brush_count()} 格）"
            )

    def _on_path_mode_toggled(self, checked: bool) -> None:
        self.canvas.set_path_mode(checked)
        if self.canvas.tool in (TOOL_ROAD, TOOL_RIVER):
            self._refresh_path_status()

    def _on_path_changed(self, _count: int) -> None:
        if self.canvas.tool in (TOOL_ROAD, TOOL_RIVER):
            self._refresh_path_status()

    def _refresh_path_status(self) -> None:
        if self.canvas.tool not in (TOOL_ROAD, TOOL_RIVER):
            return
        is_road = self.canvas.tool == TOOL_ROAD
        noun = "道路" if is_road else "河流"
        if not self.canvas.path_mode:
            self.brush_value.setText("单边")
            self.brush_status.setText(f"{noun}边")
            self.status_hint.setText(
                f"工具：{noun}边  ·  点击/拖动六边形边，每条笔触独立；右键擦边"
            )
            return
        count = self.canvas.path_point_count()
        self.brush_value.setText("路径点" if count == 0 else f"路径点 {count}")
        self.brush_status.setText(f"{noun}路径点")
        if count:
            self.status_hint.setText(
                f"{noun}路径点 {count}  ·  左键继续加点；双击/Enter 完成；"
                "右键/Backspace 撤点；Esc 取消"
            )
        else:
            self.status_hint.setText(
                f"工具：{noun}路径点  ·  左键添加路径点，双击/Enter 完成；"
                "右键擦边；Esc 取消"
            )

    def _brush_count(self) -> int:
        r = self.brush_slider.value() - 1
        return 3 * r * (r + 1) + 1

    # ------------------------------------------------------------------ 视图
    def _sync_all_views(self, initial: bool = False) -> None:
        self.canvas.renderer.rebuild_base()
        self.canvas.update()
        self.minimap.set_image(self.model.to_minimap_image())
        self._update_stats()
        self._update_document()
        if initial:
            q = QTimer(self)
            q.singleShot(0, self.canvas.fit_to_view)
        self._update_undo_buttons()

    def _on_map_edited(self, full: bool) -> None:
        self.minimap.set_image(self.model.to_minimap_image())
        self._update_stats()
        self._update_document()
        self._update_undo_buttons()
        if full:
            self._set_seed_text(self.model.seed)

    def _on_clean_changed(self, clean: bool) -> None:
        self._update_document()

    def _update_undo_buttons(self) -> None:
        self.btn_undo.setEnabled(self.undo_stack.canUndo())
        self.btn_redo.setEnabled(self.undo_stack.canRedo())

    def _update_document(self) -> None:
        dirty = self._is_dirty()
        name = self.model.name or "未命名大陆"
        self.doc_name.setText(("*  " if dirty else "") + name)
        self.doc_meta.setText(
            f"{self.model.width} × {self.model.height}  ·  种子 {self.model.seed}"
        )
        if self.name_edit.text() != name and not self.name_edit.hasFocus():
            self.name_edit.setText(name)
        self.setWindowTitle(
            f"{'* ' if dirty else ''}{name} · SimpleKingdom 地图工坊"
        )

    def _update_stats(self) -> None:
        stats = self.model.stats()
        total = self.model.cell_count
        land = total - stats.terrain_counts.get(int(Terrain.OCEAN), 0)
        ratio = land / total * 100 if total else 0
        lakes = self.model.count_terrain_components(Terrain.LAKE)
        lake_cells = stats.terrain_counts.get(int(Terrain.LAKE), 0)
        rivers = len(self.model.river_groups)
        river_edges = sum(mask.bit_count() for mask in self.model.river_edges)
        roads = len(self.model.road_groups)
        road_edges = sum(mask.bit_count() for mask in self.model.road_edges)
        self.stat_land.set_value(f"{ratio:.1f}%", f"{land:,} 格陆地")
        self.stat_lake.set_value(f"{lakes} 处", f"{lake_cells:,} 格水域")
        self.stat_river.set_value(f"{rivers} 条", f"{river_edges:,} 条边")
        self.stat_road.set_value(f"{roads} 条", f"{road_edges:,} 条边")

    # ------------------------------------------------------------------ 文件
    def _is_dirty(self) -> bool:
        return (not self.undo_stack.isClean()) or self._extra_dirty

    def _confirm_discard(self) -> bool:
        if not self._is_dirty():
            return True
        box = QMessageBox(self)
        box.setWindowTitle("尚未保存")
        box.setText("这片大陆还没有保存。")
        box.setInformativeText("要先保存当前地图吗？")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        result = box.exec()
        if result == QMessageBox.StandardButton.Save:
            return self.save_map()
        if result == QMessageBox.StandardButton.Discard:
            return True
        return False

    def new_map(self) -> None:
        if not self._confirm_discard():
            return
        self.model.fill(Terrain.OCEAN)
        self.model.name = "未命名大陆"
        self.model.seed = random.SystemRandom().randrange(1, 2_000_000_000)
        self.model.file_path = None
        self._current_file = None
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self._extra_dirty = False
        self.canvas.refresh_full()
        self.canvas.fit_to_view()
        self.minimap.set_model(self.model)
        self.minimap.set_image(self.model.to_minimap_image())
        self._set_seed_text(self.model.seed)
        self.name_edit.setText(self.model.name)
        self._update_stats()
        self._update_document()
        self._toast("已新建空白海域")

    def open_map(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开地图",
            str(Path.home()),
            "SimpleKingdom 地图 (*.skmap);;所有文件 (*)",
        )
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            model, _snapshot = load_map(path)
        except (OSError, MapFormatError) as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "无法打开地图", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self.model = model
        self._current_file = path
        self.model.file_path = path
        self.canvas.set_model(model)
        self.minimap.set_model(model)
        self.minimap.set_image(model.to_minimap_image())
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self._extra_dirty = False
        self.name_edit.setText(model.name)
        self._set_seed_text(model.seed)
        self._update_stats()
        self._update_document()
        self._toast(f"已打开 {Path(path).name}")

    def save_map(self) -> bool:
        if not self._current_file:
            return self.save_map_as()
        return self._write_map(self._current_file)

    def save_map_as(self) -> bool:
        default = (self.model.name or "未命名大陆") + ".skmap"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存地图",
            str(Path.home() / default),
            "SimpleKingdom 地图 (*.skmap)",
        )
        if not path:
            return False
        if not path.lower().endswith(".skmap"):
            path += ".skmap"
        return self._write_map(path)

    def _write_map(self, path: str) -> bool:
        self.model.name = self.name_edit.text().strip() or "未命名大陆"
        try:
            save_map(self.model, path)
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return False
        self._current_file = path
        self.model.file_path = path
        self.undo_stack.setClean()
        self._extra_dirty = False
        self._update_document()
        self._toast(f"已保存到 {Path(path).name}")
        return True

    def export_png(self) -> None:
        default = (self.model.name or "未命名大陆") + ".png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出地图图片",
            str(Path.home() / default),
            "PNG 图片 (*.png)",
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status_hint.setText("正在导出地图图片…")
        QApplication.processEvents()
        try:
            image = render_overview(self.model, 2400)
            ok = image.save(path, "PNG")
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self.status_hint.setText(
            "就绪 · 左键绘制，右键擦边；橡皮擦可清除地块与路径"
        )
        if ok:
            self._toast(f"已导出 {Path(path).name}")
        else:
            QMessageBox.critical(self, "导出失败", "PNG 文件写入失败。")

    def undo(self) -> None:
        self.undo_stack.undo()

    def redo(self) -> None:
        self.undo_stack.redo()

    def _on_name_edited(self) -> None:
        name = self.name_edit.text().strip() or "未命名大陆"
        if name != self.model.name:
            self.model.name = name
            self._extra_dirty = True
            self._update_document()

    def _set_seed_text(self, seed: int) -> None:
        self.seed_edit.blockSignals(True)
        self.seed_edit.setText(str(seed))
        self.seed_edit.blockSignals(False)

    # ------------------------------------------------------------------ 随机生成
    def _randomize_seed(self) -> None:
        self._set_seed_text(random.SystemRandom().randrange(1, 2_000_000_000))

    def open_generator(self) -> None:
        if self._gen_worker is not None and self._gen_worker.isRunning():
            return
        try:
            seed = int(self.seed_edit.text())
        except ValueError:
            seed = random.SystemRandom().randrange(1, 2_000_000_000)
            self._set_seed_text(seed)
        if seed <= 0:
            seed = random.SystemRandom().randrange(1, 2_000_000_000)
            self._set_seed_text(seed)
        params = {
            "width": self.model.width,
            "height": self.model.height,
            "seed": seed,
            "land_ratio": self.sliders["land"][0].value() / 100.0,
            "island_amount": self.sliders["islands"][0].value() / 100.0,
            "lake_amount": self.sliders["lakes"][0].value() / 100.0,
            "river_amount": self.sliders["rivers"][0].value() / 100.0,
        }
        dialog = QProgressDialog("正在塑造大陆轮廓…", None, 0, 100, self)
        dialog.setWindowTitle("随机生成大陆")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        dialog.setFixedWidth(420)
        dialog.show()
        worker = GenerationWorker(params, self)
        self._gen_worker = worker
        self._gen_dialog = dialog
        worker.progressed.connect(self._on_generation_progress)
        worker.succeeded.connect(self._on_generation_success)
        worker.failed.connect(self._on_generation_failed)
        worker.finished.connect(self._on_generation_finished)
        worker.start()

    def _on_generation_progress(self, value: int, text: str) -> None:
        dialog = self._gen_dialog
        if dialog is None:
            return
        try:
            dialog.setLabelText(text)
            dialog.setValue(value)
        except RuntimeError:
            # 弹窗可能在信号排队期间已经销毁。
            self._gen_dialog = None

    def _on_generation_finished(self) -> None:
        if self._gen_dialog is not None:
            self._gen_dialog.close()
            self._gen_dialog.deleteLater()
            self._gen_dialog = None
        if self._gen_worker is not None:
            self._gen_worker.deleteLater()
            self._gen_worker = None

    def _on_generation_failed(self, message: str) -> None:
        QMessageBox.critical(self, "生成失败", f"地形生成过程中发生错误：\n{message}")

    def _on_generation_success(self, result: GenerationResult) -> None:
        if self._gen_dialog is not None:
            self._gen_dialog.setValue(100)
            self._gen_dialog.setLabelText("正在绘制地图缓存…")
            self._gen_dialog.close()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            name = self.name_edit.text().strip() or "未命名大陆"
            before = self.model.snapshot()
            before_meta = (self.model.seed, self.model.name)
            self.model.set_arrays(result.terrain, result.overlay)
            for specs in result.river_edge_specs:
                self.model.add_river_edge_group(specs)
            self.model.rebuild_all_edges()
            self.model.seed = result.seed
            self.model.name = name
            after = self.model.snapshot()
            after_meta = (result.seed, name)
            command = WholeMapCommand(
                self.model,
                before,
                after,
                before_meta,
                after_meta,
                self.canvas._command_callback,
                "随机生成大陆",
                already_applied=True,
            )
            self.undo_stack.push(command)
        finally:
            QApplication.restoreOverrideCursor()
        self._set_seed_text(result.seed)
        self._update_document()
        self._update_stats()
        self.minimap.set_image(self.model.to_minimap_image())
        self._toast(
            f"新大陆诞生 · {result.lake_count} 处湖泊 · {result.river_count} 条河流",
            3200,
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        central = self.centralWidget()
        if central is not None and self.toast.isVisible():
            self.toast.move(
                (central.width() - self.toast.width()) // 2,
                central.height() - 74,
            )

    def _toast(self, text: str, duration: int = 2400) -> None:
        central = self.centralWidget()
        if central is not None:
            self.toast.setParent(central)
            self.toast.show_message(text, duration)
            self.toast.raise_()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._gen_worker is not None and self._gen_worker.isRunning():
            self._gen_worker.wait(3000)
        if not self._confirm_discard():
            event.ignore()
            return
        event.accept()
