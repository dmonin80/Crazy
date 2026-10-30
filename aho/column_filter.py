"""Column value filters with Excel-style checkboxes."""
from PySide6 import QtCore, QtGui, QtWidgets as W


def value_text(row,key):
    return str(row.get(key,1 if key=='quantity' else ''))


def matches(row,filters,exclude=None):
    return all(value_text(row,key) in values for key,values in filters.items() if key!=exclude)


class FilterHeader(W.QHeaderView):
    filterRequested=QtCore.Signal(int)
    def __init__(self,parent=None):
        super().__init__(QtCore.Qt.Orientation.Horizontal,parent)
        self.active=set();self.setSectionsClickable(True);self.setStyleSheet('QHeaderView::section {padding-right:24px;}')
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos:self.filterRequested.emit(self.logicalIndexAt(pos)) if self.logicalIndexAt(pos)>=0 else None)
    def paintSection(self,painter,rect,index):
        super().paintSection(painter,rect,index)
        painter.save()
        area=QtCore.QRect(rect.right()-22,rect.top()+3,20,max(16,rect.height()-6))
        painter.fillRect(area,QtGui.QColor('#d0e5f5' if index in self.active else '#e8eff5'))
        painter.setPen(QtGui.QColor('#1265a2' if index in self.active else '#526879'))
        painter.drawText(area,QtCore.Qt.AlignmentFlag.AlignCenter,'▼' if index not in self.active else '●')
        painter.restore()
    def mousePressEvent(self,event):
        index=self.logicalIndexAt(event.position().toPoint())
        if index>=0 and event.button()==QtCore.Qt.MouseButton.LeftButton and event.position().x()>=self.sectionViewportPosition(index)+self.sectionSize(index)-24:
            self.filterRequested.emit(index);event.accept();return
        super().mousePressEvent(event)


class ColumnFilterDialog(W.QDialog):
    def __init__(self,parent,label,values,selected):
        super().__init__(parent);self.setWindowTitle('Фильтр: '+label.replace('\n',' '));self.resize(360,490)
        self.result_values=None;self.sort_order=None
        layout=W.QVBoxLayout(self)
        for caption,order in [('Сортировка от А до Я / по возрастанию',QtCore.Qt.SortOrder.AscendingOrder),('Сортировка от Я до А / по убыванию',QtCore.Qt.SortOrder.DescendingOrder)]:
            button=W.QPushButton(caption);button.clicked.connect(lambda checked=False,o=order:self.sort(o));layout.addWidget(button)
        clear=W.QPushButton('Удалить фильтр из этого столбца');clear.clicked.connect(self.clear_filter);layout.addWidget(clear)
        self.search=W.QLineEdit();self.search.setPlaceholderText('Поиск значений');layout.addWidget(self.search)
        self.all=W.QCheckBox('(Выделить все)');layout.addWidget(self.all)
        self.list=W.QListWidget();layout.addWidget(self.list)
        for value in sorted(values,key=str.casefold):
            item=W.QListWidgetItem(value if value else '(Пустые)');item.setData(QtCore.Qt.ItemDataRole.UserRole,value);item.setFlags(item.flags()|QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked if selected is None or value in selected else QtCore.Qt.CheckState.Unchecked);self.list.addItem(item)
        self.search.textChanged.connect(self.search_values);self.all.clicked.connect(self.select_all);self.list.itemChanged.connect(self.update_all)
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok|W.QDialogButtonBox.StandardButton.Cancel);buttons.button(W.QDialogButtonBox.StandardButton.Cancel).setText('Отмена');layout.addWidget(buttons);buttons.accepted.connect(self.submit);buttons.rejected.connect(self.reject)
        self.update_all()
    def items(self):return [self.list.item(i) for i in range(self.list.count())]
    def search_values(self,text):
        for item in self.items():item.setHidden(text.casefold() not in item.text().casefold())
        self.update_all()
    def update_all(self,*args):
        states=[i.checkState()==QtCore.Qt.CheckState.Checked for i in self.items() if not i.isHidden()]
        self.all.setCheckState(QtCore.Qt.CheckState.Checked if states and all(states) else QtCore.Qt.CheckState.PartiallyChecked if any(states) else QtCore.Qt.CheckState.Unchecked)
    def select_all(self,checked):
        self.list.blockSignals(True)
        for item in self.items():
            if not item.isHidden():item.setCheckState(QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)
        self.list.blockSignals(False);self.update_all()
    def submit(self):
        self.result_values={i.data(QtCore.Qt.ItemDataRole.UserRole) for i in self.items() if i.checkState()==QtCore.Qt.CheckState.Checked and not i.isHidden()};self.accept()
    def clear_filter(self):self.result_values=None;self.accept()
    def sort(self,order):self.sort_order=order;self.accept()
