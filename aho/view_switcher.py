"""Two prominent buttons for the main warehouse views."""

from PySide6 import QtCore, QtWidgets as W


class ViewSwitcher(W.QWidget):
    currentChanged = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._index = 0
        layout = W.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.group = W.QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for index, text in enumerate(("Нулевой склад", "Имущество по складам")):
            button = W.QPushButton(text)
            button.setCheckable(True)
            button.setMinimumHeight(58)
            button.setSizePolicy(
                W.QSizePolicy.Policy.Expanding, W.QSizePolicy.Policy.Fixed
            )
            button.setStyleSheet(
                "QPushButton {font-size:17px;font-weight:600;padding:14px;border:1px solid #9db6ce;border-radius:7px;background:#eaf1f8;color:#173e65} QPushButton:checked {background:#245b88;color:white;border:2px solid #19486f} QPushButton:hover:!checked {background:#dceafb}"
            )
            self.group.addButton(button, index)
            self.buttons.append(button)
            layout.addWidget(button, 1)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.setCurrentIndex)

    def currentIndex(self):
        return self._index

    def tabText(self, index):
        return self.buttons[index].text()

    def setCurrentIndex(self, index):
        if index not in (0, 1):
            return
        self.buttons[index].setChecked(True)
        if self._index != index:
            self._index = index
            self.currentChanged.emit(index)
