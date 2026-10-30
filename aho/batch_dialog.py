"""Atomic transfer of several selected item types to one destination."""
import uuid
import httpx
from PySide6 import QtCore,QtWidgets as W
from .stock_dialog import StockMoveDialog
from .reference_widgets import ReferenceCombo


class BatchStockDialog(W.QDialog):
    def __init__(self,client,stocks):
        super().__init__(client);self.client=client;self.stocks=stocks;self.pending=None;self.result=None
        self.setWindowTitle('Групповое перемещение с Нулевого склада');self.resize(1000,800)
        layout=W.QVBoxLayout(self)
        title=W.QLabel(f'Выбрано наименований: {len(stocks)}. Одно назначение для всего списка.');title.setWordWrap(True);layout.addWidget(title)
        catalogs=client.api('/catalogs');assets=client.api('/assets')
        self.locations=[r for r in catalogs['locations'] if not r['archived'] and r['id']!='zero']
        form=W.QFormLayout();layout.addLayout(form)
        self.warehouse=W.QComboBox();self.warehouse.addItem('— выберите склад —',None)
        for row in self.locations:
            if row['parent'] is None:self.warehouse.addItem(row['name'],row['id'])
        self.room=W.QComboBox();self.floor=W.QLineEdit();self.floor.setPlaceholderText('Этаж места назначения')
        form.addRow('Склад для всего списка:',self.warehouse);form.addRow('Подсклад / кабинет:',self.room);form.addRow('Этаж:',self.floor)
        self.warehouse.currentIndexChanged.connect(self.update_rooms);self.update_rooms()
        self.tabs=W.QTabWidget();layout.addWidget(self.tabs,1);self.editors=[]
        for row in stocks:
            editor=StockMoveDialog(client,row,embedded=True,catalogs=catalogs,all_assets=assets)
            self.editors.append(editor);index=self.tabs.addTab(editor,row['code']);self.tabs.setTabToolTip(index,row['name'])
        details=W.QFormLayout();layout.addLayout(details)
        self.responsible=ReferenceCombo(catalogs['responsibles'],'Не назначать новым / сохранить у возвращённых')
        self.supplier=ReferenceCombo(catalogs['suppliers'],'Не назначать новым / сохранить у возвращённых')
        self.date=W.QDateEdit(QtCore.QDate.currentDate());self.date.setCalendarPopup(True);self.date.setDisplayFormat('dd.MM.yyyy')
        self.number=W.QLineEdit();self.comment=W.QLineEdit()
        for label,widget in [('Ответственное лицо:',self.responsible),('Поставщик:',self.supplier),('Дата документа:',self.date),('Номер документа:',self.number),('Комментарий:',self.comment)]:details.addRow(label,widget)
        self.error=W.QLabel();self.error.setWordWrap(True);self.error.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse);self.error.setStyleSheet('color:#ae2020');layout.addWidget(self.error)
        bar=W.QHBoxLayout();layout.addLayout(bar)
        self.check=W.QPushButton('Проверить результат');self.check.hide();self.check.clicked.connect(self.check_result);bar.addWidget(self.check)
        bar.addStretch();cancel=W.QPushButton('Отмена');cancel.clicked.connect(self.reject);bar.addWidget(cancel)
        self.submit_button=W.QPushButton('Переместить весь список');self.submit_button.clicked.connect(self.submit);bar.addWidget(self.submit_button)

    def update_rooms(self):
        self.room.clear();self.room.addItem('Без подсклада — на самом складе',None)
        parent=self.warehouse.currentData()
        for row in self.locations:
            if parent and row['parent']==parent:self.room.addItem(row['name'],row['id'])

    def payload(self):
        parent=self.warehouse.currentData()
        if not parent:raise ValueError('Выберите склад назначения для списка')
        destination=self.room.currentData() or parent
        p={'destination':destination,'date':self.date.date().toString('yyyy-MM-dd'),'number':self.number.text(),'comment':self.comment.text(),'floor':self.floor.text(),'lines':[]}
        for key,combo in [('responsible_id',self.responsible),('supplier_id',self.supplier)]:
            value=combo.selected_id()
            if value is not None:p[key]=value
        for index,editor in enumerate(self.editors):
            editor.warehouse.setCurrentIndex(editor.warehouse.findData(parent))
            editor.room.setCurrentIndex(editor.room.findData(self.room.currentData()))
            try:path,line=editor.payload()
            except ValueError as exc:
                self.tabs.setCurrentIndex(index);raise ValueError(editor.stock['name']+': '+str(exc)) from exc
            selected={'item_id':editor.stock['id'],'kind':'allocate' if path=='/allocate' else 'move'}
            for key in ('quantity','suffixes','note','assets'):
                if key in line:selected[key]=line[key]
            p['lines'].append(selected)
        return p

    def submit(self):
        if self.pending:return
        try:p=self.payload()
        except ValueError as exc:self.error.setText(str(exc));return
        p['request_id']=str(uuid.uuid4());self.pending=p;self.submit_button.setEnabled(False)
        try:self.result=self.client.api('/batch-transfer',p)
        except Exception as exc:
            self.error.setText(str(exc))
            if isinstance(exc.__cause__,httpx.TransportError):
                self.check.show();self.error.setText('Результат неопределён. Проверьте исходный запрос: '+p['request_id'])
            else:self.pending=None;self.submit_button.setEnabled(True)
            return
        self.accept()

    def check_result(self):
        if not self.pending:return
        try:self.result=self.client.api('/requests/'+self.pending['request_id'])
        except Exception as exc:self.error.setText(str(exc));return
        self.accept()
