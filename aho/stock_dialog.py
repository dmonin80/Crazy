"""Movement from a clicked row in the Zero Warehouse table."""
import uuid

import httpx
from PySide6 import QtCore, QtWidgets as W
from .reference_widgets import ReferenceCombo
from .quantities import quantity,number as qnumber,total as qtotal
from .quantity_widgets import DecimalInput


class StockMoveDialog(W.QDialog):
    def __init__(self, client, stock, embedded=False, catalogs=None, all_assets=None):
        super().__init__(client)
        self.client = client
        self.stock = stock
        self.quantitative=stock.get('tracking_mode')=='quantity'
        self.pending = None
        self.result = None
        self.setWindowTitle('Перемещение с Нулевого склада')
        self.resize(820, 630)
        layout = W.QVBoxLayout(self)
        name = W.QLabel(stock['name']); name.setWordWrap(True)
        name.setStyleSheet('font-size:17px;font-weight:600;color:#16324F')
        layout.addWidget(name)
        layout.addWidget(W.QLabel('Код: ' + stock['code'] + ' · Единица: ' + stock['unit']))
        layout.addWidget(W.QLabel(f"Нераспределено: {stock['unassigned']} · Возвращено: {stock['returned']} · Доступно: {qnumber(qtotal([stock['unassigned'],stock['returned']]))}"))
        catalogs = catalogs if catalogs is not None else client.api('/catalogs')
        self.locations = [r for r in catalogs['locations'] if not r.get('archived') and r['id'] != 'zero']
        form = W.QFormLayout(); layout.addLayout(form)
        self.warehouse = W.QComboBox(); self.warehouse.addItem('— выберите склад —', None)
        for row in self.locations:
            if row['parent'] is None:
                self.warehouse.addItem(row['name'], row['id'])
        self.room = W.QComboBox()
        self.warehouse.currentIndexChanged.connect(self.update_rooms)
        self.room.currentIndexChanged.connect(self.update_destination)
        form.addRow('Склад назначения:', self.warehouse)
        form.addRow('Подсклад / кабинет:', self.room)
        self.floor = W.QLineEdit()
        self.floor.setPlaceholderText('Этаж выбранного места: 1, 2, цоколь, технический')
        form.addRow('Этаж:', self.floor)
        self.destination_label = W.QLabel(''); self.destination_label.setWordWrap(True)
        form.addRow('Итоговое размещение:', self.destination_label)
        self.sources = W.QTabWidget(); layout.addWidget(self.sources, 1)
        fresh = W.QWidget(); fresh_layout = W.QFormLayout(fresh)
        fresh_layout.addRow(W.QLabel('Количественный учёт: одна карточка на указанное количество.' if self.quantitative else 'Целое штучное количество — отдельные карточки; дробное — одна количественная карточка.'))
        self.quantity=DecimalInput('0' if self.quantitative else ('1' if quantity(stock['unassigned'])>0 else '0'))
        fresh_layout.addRow('Количество к перемещению:', self.quantity)
        hint=W.QLabel('Введите дополнение для каждой карточки, включая нужный разделитель. Например: -1 или /А-01. Исходный код изменять нельзя.')
        hint.setWordWrap(True);fresh_layout.addRow(hint)
        self.suffix_table=W.QTableWidget(0,2)
        self.suffix_table.setHorizontalHeaderLabels(['Дополнение к коду — введите вручную','Итоговый инвентарный номер'])
        self.suffix_table.setMinimumHeight(120)
        self.suffix_table.setColumnWidth(0,300);self.suffix_table.horizontalHeader().setStretchLastSection(True)
        self.suffix_table.itemChanged.connect(self.update_number_preview)
        fresh_layout.addRow(self.suffix_table)
        self.quantity.valueChanged.connect(self.resize_suffixes)
        self.resize_suffixes()
        self.note = W.QLineEdit(); fresh_layout.addRow('Примечание карточек:', self.note)
        self.sources.addTab(fresh, 'Нераспределённые единицы')
        returned_page = W.QWidget(); returned_layout = W.QVBoxLayout(returned_page)
        returned_layout.addWidget(W.QLabel('Отметьте существующие карточки. Их номера и QR-коды сохранятся.'))
        self.returned = [r for r in (all_assets if all_assets is not None else client.api('/assets')) if r['item_id'] == stock['id'] and r['location'] == 'zero']
        self.returned_table = W.QTableWidget(len(self.returned), 4)
        self.returned_table.setHorizontalHeaderLabels(['Выбрать', 'Инвентарный номер', 'Ответственное лицо','Количество'])
        self.returned_table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.returned_table.horizontalHeader().setStretchLastSection(True)
        for n, row in enumerate(self.returned):
            check = W.QTableWidgetItem(); check.setCheckState(QtCore.Qt.CheckState.Unchecked)
            self.returned_table.setItem(n, 0, check)
            self.returned_table.setItem(n, 1, W.QTableWidgetItem(row['number']))
            self.returned_table.setItem(n, 2, W.QTableWidgetItem(row['responsible']))
            self.returned_table.setItem(n,3,W.QTableWidgetItem(str(row.get('quantity',1))))
        self.returned_table.resizeColumnsToContents()
        returned_layout.addWidget(self.returned_table)
        self.sources.addTab(returned_page, 'Возвращённые карточки')
        self.sources.setTabEnabled(0, quantity(stock['unassigned']) > 0)
        self.sources.setTabEnabled(1, bool(self.returned))
        if quantity(stock['unassigned']) == 0 and self.returned:
            self.sources.setCurrentIndex(1)
        details = W.QFormLayout(); layout.addLayout(details)
        self.responsible = ReferenceCombo(catalogs['responsibles'],'Не назначено')
        self.supplier = ReferenceCombo(catalogs['suppliers'],'Не указан')
        self.document_date = W.QDateEdit(QtCore.QDate.currentDate()); self.document_date.setCalendarPopup(True)
        self.document_date.setDisplayFormat('dd.MM.yyyy')
        self.number = W.QLineEdit(); self.comment = W.QLineEdit()
        details.addRow('Ответственное лицо:', self.responsible)
        details.addRow('Поставщик:', self.supplier)
        details.addRow('Дата документа:', self.document_date)
        details.addRow('Номер документа:', self.number)
        details.addRow('Комментарий движения:', self.comment)
        self.error = W.QLabel(); self.error.setWordWrap(True); self.error.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error.setStyleSheet('color:#DC2626'); layout.addWidget(self.error)
        buttons = W.QHBoxLayout(); layout.addLayout(buttons)
        self.check_button = W.QPushButton('Проверить результат запроса'); self.check_button.hide()
        self.check_button.clicked.connect(self.check_result); buttons.addWidget(self.check_button)
        buttons.addStretch()
        cancel = W.QPushButton('Отмена'); cancel.clicked.connect(self.reject); buttons.addWidget(cancel)
        self.submit_button = W.QPushButton('Переместить'); self.submit_button.clicked.connect(self.submit); buttons.addWidget(self.submit_button)
        if not self.locations:
            self.error.setText('Сначала создайте склад или подсклад через «Справочники». ')
        self.sources.currentChanged.connect(self.update_reference_placeholders)
        self.update_reference_placeholders()
        self.update_rooms()
        if embedded:
            self.setWindowFlags(QtCore.Qt.WindowType.Widget)
            for hidden_form in (form,details):
                for index in range(hidden_form.count()):
                    widget=hidden_form.itemAt(index).widget()
                    if widget:widget.hide()
            for index in range(buttons.count()):
                widget=buttons.itemAt(index).widget()
                if widget:widget.hide()
            self.error.hide()

    def resize_suffixes(self,*_):
        self.suffix_table.blockSignals(True)
        try:
            try:amount=self.quantity.value()
            except ValueError:amount=quantity(0)
            count=1 if self.quantitative or amount!=amount.to_integral_value() else min(10000,int(amount))
            self.suffix_table.setRowCount(count)
            for row in range(count):
                if self.suffix_table.item(row,0) is None:self.suffix_table.setItem(row,0,W.QTableWidgetItem(''))
                preview=W.QTableWidgetItem()
                preview.setFlags(preview.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                self.suffix_table.setItem(row,1,preview)
        finally:self.suffix_table.blockSignals(False)
        for row in range(self.suffix_table.rowCount()):self.update_number_preview(self.suffix_table.item(row,0))

    def update_number_preview(self,item):
        if item.column()!=0:return
        value=item.text()
        if hasattr(self,'error') and self.pending is None:self.error.clear()
        preview=self.suffix_table.item(item.row(),1)
        if preview is not None:
            preview.setText(self.stock['code']+value if value else 'Введите дополнение к коду')
            preview.setToolTip(preview.text())

    def update_reference_placeholders(self):
        keep=self.sources.currentIndex()==1
        self.responsible.setItemText(0,'Сохранить прежнего ответственного' if keep else 'Не назначено')
        self.supplier.setItemText(0,'Сохранить прежнего поставщика' if keep else 'Не указан')

    def update_rooms(self):
        self.room.blockSignals(True)
        self.room.clear(); self.room.addItem('Без подсклада — разместить на самом складе', None)
        parent = self.warehouse.currentData()
        for row in self.locations:
            if row['parent'] == parent and parent is not None:
                self.room.addItem(row['name'], row['id'])
        self.room.setEnabled(parent is not None)
        self.room.blockSignals(False)
        self.update_destination()

    def update_destination(self):
        destination = self.warehouse.currentData()
        text = self.warehouse.currentText() if destination else 'Выберите склад'
        if self.room.currentData():
            text += ' / ' + self.room.currentText()
        self.destination_label.setText(text)
        self.submit_button.setEnabled(bool(destination) and self.pending is None and (quantity(self.stock['unassigned']) > 0 or bool(self.returned)))

    def payload(self):
        warehouse = self.warehouse.currentData()
        if not warehouse:
            raise ValueError('Выберите склад назначения')
        destination = self.room.currentData() or warehouse
        payload = {'destination': destination, 'date': self.document_date.date().toString('yyyy-MM-dd'),
                   'number': self.number.text(), 'comment': self.comment.text(), 'floor': self.floor.text()}
        if self.sources.currentIndex() == 0:
            if self.quantity.value() <= 0:
                raise ValueError('Нет нераспределённого остатка')
            suffixes=[self.suffix_table.item(row,0).text() for row in range(self.suffix_table.rowCount())]
            if any(not value.strip() for value in suffixes):
                raise ValueError('Введите дополнение к коду для каждой единицы в таблице номеров')
            if len(set(suffixes))!=len(suffixes):
                raise ValueError('Дополнения к коду должны различаться у разных единиц')
            payload.update(item_id=self.stock['id'], quantity=qnumber(self.quantity.value()),suffixes=suffixes,
                           responsible_id=self.responsible.selected_id(),supplier_id=self.supplier.selected_id(), note=self.note.text())
            return '/allocate', payload
        selected = [row for n, row in enumerate(self.returned)
                    if self.returned_table.item(n, 0).checkState() == QtCore.Qt.CheckState.Checked]
        if not selected:
            raise ValueError('Отметьте возвращённые карточки для перемещения')
        payload.update(source='zero', assets=[{'id': r['id'], 'version': r['version']} for r in selected])
        responsible=self.responsible.selected_id()
        supplier=self.supplier.selected_id()
        if responsible is not None:payload['responsible_id']=responsible
        if supplier is not None:payload['supplier_id']=supplier
        return '/move', payload

    def submit(self):
        if self.pending is not None:
            return
        self.error.clear()
        try:
            path, payload = self.payload()
        except ValueError as exc:
            self.error.setText(str(exc)); return
        payload['request_id'] = str(uuid.uuid4())
        self.pending = (path, payload)
        self.submit_button.setEnabled(False)
        try:
            self.result = self.client.api(path, payload)
        except Exception as exc:
            if isinstance(exc.__cause__, httpx.TransportError):
                self.error.setText('Ответ не получен. Результат неопределён. Нажмите «Проверить результат запроса». ID: ' + payload['request_id'])
                self.check_button.show()
            else:
                self.pending = None
                self.error.setText(str(exc))
                self.update_destination()
            return
        self.accept()

    def check_result(self):
        if self.pending is None:
            return
        try:
            self.result = self.client.api('/requests/' + self.pending[1]['request_id'])
        except Exception as exc:
            self.error.setText('Результат пока не подтверждён. Повторите проверку; новая команда не отправляется. ID: ' + self.pending[1]['request_id'] + '\n' + str(exc))
            return
        self.accept()
