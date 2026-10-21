"""SimpleKingdom 入口。

运行：
    python main.py
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from simplekingdom.style import APP_STYLESHEET
from simplekingdom.ui import MapEditorWindow
from simplekingdom.widgets import make_app_icon


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("SimpleKingdom")
    app.setApplicationDisplayName("SimpleKingdom 地图工坊")
    app.setOrganizationName("SimpleKingdom")
    app.setStyle("Fusion")
    app.setWindowIcon(make_app_icon())
    font = QFont("Microsoft YaHei UI", 9)
    if not font.exactMatch():
        font = QFont("Microsoft YaHei", 9)
    app.setFont(font)
    app.setStyleSheet(APP_STYLESHEET)
    window = MapEditorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
