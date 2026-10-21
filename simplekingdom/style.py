"""应用视觉样式。"""

from __future__ import annotations

APP_STYLESHEET = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
}
QMainWindow, QDialog {
    background: #0a1117;
    color: #cbd6dc;
}
QWidget {
    color: #c9d4da;
    font-size: 12px;
}
QFrame#Header {
    background: #101a22;
    border-bottom: 1px solid #22313a;
}
QFrame#Panel {
    background: #101920;
    border: none;
}
QFrame#PanelEdgeLeft {
    background: #101920;
    border-right: 1px solid #1e2b34;
}
QFrame#PanelEdgeRight {
    background: #101920;
    border-left: 1px solid #1e2b34;
}
QFrame#Separator {
    background: #223039;
    max-height: 1px;
    min-height: 1px;
    border: none;
}
QFrame#VSeparator {
    background: #26343d;
    max-width: 1px;
    min-width: 1px;
    border: none;
}
QFrame#Card {
    background: #152029;
    border: 1px solid #24333d;
    border-radius: 10px;
}
QFrame#ZoomPanel {
    background: #111c24;
    border: 1px solid #2a3a44;
    border-radius: 9px;
}
QLabel {
    background: transparent;
}
QLabel#BrandTop {
    color: #d8b45a;
    font-size: 9px;
    font-weight: 600;
}
QLabel#BrandBottom {
    color: #f0e8d7;
    font-size: 17px;
    font-weight: 700;
}
QLabel#DocName {
    color: #d6dfe3;
    font-size: 12px;
    font-weight: 600;
}
QLabel#DocMeta {
    color: #6f828c;
    font-size: 10px;
}
QLabel#PanelTitle {
    color: #ede5d4;
    font-size: 15px;
    font-weight: 700;
}
QLabel#PanelSubtitle {
    color: #768a94;
    font-size: 10px;
}
QLabel#SectionLabel {
    color: #7e929c;
    font-size: 10px;
    font-weight: 600;
    padding-top: 2px;
}
QLabel#Hint {
    color: #71848d;
    font-size: 10px;
}
QLabel#ValueLabel {
    color: #d8e1e4;
    font-size: 11px;
}
QLabel#ZoomPercent {
    color: #b9c6cd;
    font-size: 10px;
}
QLabel#StatusText {
    color: #91a3ac;
    font-size: 11px;
}
QLabel#StatusAccent {
    color: #d8b45a;
    font-size: 12px;
}
QLabel#StatusDivider {
    color: #2e3d46;
    font-size: 11px;
}
QPushButton#TerrainButton {
    background: #152029;
    border: 1px solid #263640;
    border-radius: 8px;
    text-align: left;
    padding: 6px 8px;
    color: #c8d3d8;
    font-size: 12px;
    font-weight: 500;
}
QPushButton#TerrainButton:hover {
    background: #1a2832;
    border-color: #405562;
}
QPushButton#TerrainButton:checked {
    background: #283226;
    border: 1px solid #d8b45a;
    color: #f7efdd;
}
QPushButton#OverlayButton {
    background: #152029;
    border: 1px solid #263640;
    border-radius: 8px;
    text-align: left;
    padding: 7px 10px;
    color: #c8d3d8;
    font-size: 12px;
}
QPushButton#OverlayButton:hover {
    background: #1a2832;
    border-color: #405562;
}
QPushButton#OverlayButton:checked {
    background: #283226;
    border: 1px solid #d8b45a;
    color: #f7efdd;
}
QToolButton#HeaderButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    color: #c7d2d7;
    padding: 5px 9px;
    font-size: 11px;
}
QToolButton#HeaderButton:hover {
    background: #1b2932;
    border-color: #2e404b;
    color: #f2ebdb;
}
QToolButton#HeaderButton:pressed {
    background: #142028;
}
QToolButton#IconButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px;
}
QToolButton#IconButton:hover {
    background: #1b2932;
    border-color: #2e404b;
}
QToolButton#GenerateButton {
    background: #d8b45a;
    border: 1px solid #e5c777;
    border-radius: 8px;
    color: #172019;
    padding: 6px 13px;
    font-size: 12px;
    font-weight: 700;
}
QToolButton#GenerateButton:hover {
    background: #e6c66f;
}
QToolButton#GenerateButton:pressed {
    background: #c5a24a;
}
QToolButton#ZoomButton {
    background: transparent;
    border: none;
    border-radius: 5px;
    color: #b6c4ca;
    font-size: 14px;
}
QToolButton#ZoomButton:hover {
    background: #21323c;
    color: #f0e7d4;
}
QLineEdit {
    background: #0f181f;
    border: 1px solid #283942;
    border-radius: 6px;
    padding: 6px 8px;
    color: #e3e9eb;
    selection-background-color: #8c743f;
    font-size: 12px;
}
QLineEdit:focus {
    border: 1px solid #a98c4e;
    background: #111c24;
}
QLineEdit#SeedInput {
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}
QSpinBox {
    background: #0f181f;
    border: 1px solid #283942;
    border-radius: 6px;
    padding: 4px 6px;
    color: #e3e9eb;
    min-width: 46px;
}
QSpinBox:focus {
    border-color: #a98c4e;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 14px;
    border: none;
    background: transparent;
}
QCheckBox {
    color: #9fb1b8;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 13px;
    height: 13px;
    border: 1px solid #3a4b54;
    border-radius: 3px;
    background: #0d151a;
}
QCheckBox::indicator:checked {
    background: #d9b866;
    border: 1px solid #f0d491;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #26343d;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #a88d4f;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #e8d7a4;
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover {
    background: #f6e8bf;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea#RightScroll {
    background: #101920;
    border: none;
}
QWidget#RightContent {
    background: #101920;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #2d3d46;
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #40535e;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QMenu {
    background: #142029;
    border: 1px solid #2b3c46;
    padding: 6px;
    color: #d5dee2;
}
QMenu::item {
    padding: 6px 26px 6px 14px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: #24343e;
}
QMenu::separator {
    height: 1px;
    background: #2b3c46;
    margin: 5px 8px;
}
QToolTip {
    background: #18242d;
    color: #e6ded0;
    border: 1px solid #3a4d58;
    padding: 5px 7px;
    border-radius: 4px;
}
QProgressDialog {
    background: #121c24;
    color: #d8e1e4;
    border: 1px solid #2c3e48;
}
QProgressBar {
    background: #0c151b;
    border: 1px solid #2b3c46;
    border-radius: 5px;
    text-align: center;
    color: #e8e0cf;
    min-height: 16px;
}
QProgressBar::chunk {
    background: #b99a4f;
    border-radius: 4px;
}
QMessageBox {
    background: #121c24;
}
QPushButton {
    color: #d5dee2;
}
QPushButton#DialogPrimary {
    background: #d8b45a;
    color: #182018;
    border: none;
    border-radius: 7px;
    padding: 7px 16px;
    font-weight: 700;
}
QPushButton#DialogPrimary:hover {
    background: #e6c66f;
}
"""
