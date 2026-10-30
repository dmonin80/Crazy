"""Shared palette and desktop styling based on the approved visual reference."""

from PySide6 import QtCore, QtGui, QtWidgets as W

FOOTER = (
    "Создано Специалистами Уральского управления по информационным технологиям\n"
    "Acron Digital (ООО «АйТиОфис» ОП «Березники») 2026"
)

STYLESHEET = """
QWidget { color: #1F2937; font-family: "Segoe UI", "DejaVu Sans"; font-size: 13px; }
QMainWindow, QDialog { background: #F3F6FA; }
QFrame#brandHeader { background: #16324F; border-radius: 8px; }
QFrame#brandHeader QLabel { color: #FFFFFF; background: transparent; }
QLabel#brandTitle { font-size: 24px; font-weight: 700; }
QLabel#brandSubtitle { color: #D8E1EC; font-size: 13px; }
QLabel#sectionTitle { color: #16324F; font-size: 22px; font-weight: 700; padding: 5px 0; }
QFrame#metric { background: #FFFFFF; border: 1px solid #D8E1EC; border-radius: 8px; }
QFrame#metric[accent="blue"] { background: #EDF4FF; }
QFrame#metric[accent="teal"] { background: #EFF9F8; }
QFrame#metric[accent="amber"] { background: #FFF8EB; }
QLabel#metricLabel { color: #60758D; font-size: 12px; }
QLabel#metricValue { color: #16324F; font-size: 24px; font-weight: 700; }
QPushButton, QToolButton { background: #FFFFFF; color: #16324F; border: 1px solid #D8E1EC; border-radius: 6px; padding: 9px 14px; font-weight: 600; }
QPushButton:hover, QToolButton:hover { background: #EDF4FF; border-color: #2563EB; }
QPushButton:pressed { background: #DCEAFF; }
QPushButton:disabled { background: #EDF1F6; color: #8B9BB0; border-color: #D8E1EC; }
QPushButton[role="primary"], QPushButton#viewTab:checked { background: #2563EB; border-color: #2563EB; color: #FFFFFF; }
QPushButton[role="primary"]:hover, QPushButton#viewTab:checked:hover { background: #1D4ED8; }
QPushButton[role="primary"]:disabled { background: #CBD9F1; color: #8195B4; border-color: #CBD9F1; }
QPushButton[role="danger"] { background: #DC2626; border-color: #DC2626; color: white; }
QPushButton[role="danger"]:hover { background: #B91C1C; }
QPushButton[role="danger"]:disabled { background: #F1DEDE; color: #9D8585; border-color: #E5D5D5; }
QPushButton[role="accent"] { background: #0F766E; border-color: #0F766E; color: white; }
QPushButton#viewTab { padding: 12px 22px; font-size: 15px; }
QPushButton#switchUser { background: transparent; color: #93C5FD; border: none; padding: 2px; text-align: right; }
QLineEdit, QComboBox, QSpinBox, QDateEdit, QTextEdit, QTextBrowser, QListWidget, QTreeWidget { background: white; border: 1px solid #D8E1EC; border-radius: 5px; padding: 6px; selection-background-color: #2563EB; selection-color: white; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus { border-color: #2563EB; }
QTableView, QTableWidget { background: #FFFFFF; alternate-background-color: #F5F8FC; border: 1px solid #D8E1EC; border-radius: 6px; gridline-color: #E4EAF2; selection-background-color: #DBEAFE; selection-color: #16324F; }
QHeaderView::section { background: #EDF2F8; color: #16324F; padding: 6px; font-size: 12px; border: none; border-right: 1px solid #D8E1EC; border-bottom: 1px solid #D8E1EC; font-weight: 600; }
QTableCornerButton::section { background: #EDF2F8; border: 1px solid #D8E1EC; }
QTabWidget::pane { background: white; border: 1px solid #D8E1EC; border-radius: 6px; }
QTabBar::tab { background: #EDF2F8; padding: 9px 15px; color: #16324F; border: 1px solid #D8E1EC; }
QTabBar::tab:selected { background: white; color: #2563EB; border-bottom: 2px solid #2563EB; }
QMenuBar { background: #16324F; color: white; padding: 3px; }
QMenuBar::item:selected { background: #25496C; }
QMenu { background: white; border: 1px solid #D8E1EC; padding: 5px; }
QMenu::item { padding: 7px 20px; }
QMenu::item:selected { background: #DBEAFE; color: #16324F; }
QStatusBar { background: #EAF0F6; color: #60758D; border-top: 1px solid #D8E1EC; }
QLabel#credits { color: #607D99; background: #EDF3F6; border-top: 1px solid #D8E1EC; padding: 10px; font-size: 10px; }
QProgressBar { border: 1px solid #D8E1EC; border-radius: 5px; background: white; text-align: center; min-height: 20px; }
QProgressBar::chunk { background: #0F766E; border-radius: 4px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QToolTip { background: #16324F; color: white; border: none; padding: 6px; }
"""


def brand_icon():
    pixmap = QtGui.QPixmap(48, 48)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(QtGui.QPen(QtGui.QColor("#16324F"), 2))
    painter.setBrush(QtGui.QColor("white"))
    for points in [
        [(24, 3), (44, 14), (24, 25), (4, 14)],
        [(4, 14), (24, 25), (24, 46), (4, 35)],
        [(24, 25), (44, 14), (44, 35), (24, 46)],
    ]:
        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y) for x, y in points]))
    painter.end()
    return pixmap


def metric(label, accent):
    frame = W.QFrame()
    frame.setObjectName("metric")
    frame.setProperty("accent", accent)
    layout = W.QVBoxLayout(frame)
    layout.setContentsMargins(16, 10, 16, 10)
    layout.setSpacing(2)
    caption = W.QLabel(label)
    caption.setObjectName("metricLabel")
    layout.addWidget(caption)
    value = W.QLabel("0")
    value.setObjectName("metricValue")
    layout.addWidget(value)
    return frame, value
