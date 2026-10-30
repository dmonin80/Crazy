from PySide6 import QtCore,QtWidgets as W
from .quantities import quantity,text


class DecimalInput(W.QLineEdit):
    valueChanged=QtCore.Signal(object)
    def __init__(self,value='0',parent=None):
        super().__init__(parent);self.setText(text(value));self.setPlaceholderText('Например: 1,25')
        self.textChanged.connect(self.changed)
    def changed(self,_):
        try:value=self.value()
        except ValueError:value=None
        self.valueChanged.emit(value)
    def value(self):return quantity(self.text())
    def setValue(self,value):self.setText(text(value))


class QuantityItem(W.QTableWidgetItem):
    def __lt__(self,other):
        try:return quantity(self.text())<quantity(other.text())
        except ValueError:return super().__lt__(other)
