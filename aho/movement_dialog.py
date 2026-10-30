"""Move existing cards using the same business directory choices."""
import uuid
from PySide6 import QtCore,QtWidgets as W
from .reference_widgets import ReferenceCombo,LocationDialog
from .quantities import quantity,number as qnumber


class MoveAssetsDialog(W.QDialog):
    def __init__(self,client,assets,back=False):
        super().__init__(client);self.client=client;self.assets=assets;self.destination='zero' if back else None
        self.setWindowTitle('Возврат на Нулевой склад' if back else 'Перемещение имущества');self.resize(690,380)
        layout=W.QFormLayout(self);layout.addRow(W.QLabel(f'Выбрано карточек: {len(assets)}'))
        self.target=W.QLabel('Нулевой склад' if back else 'Не выбран');self.target.setWordWrap(True)
        choose=W.QPushButton('Выбрать склад / подсклад');choose.setEnabled(not back);choose.clicked.connect(self.choose)
        layout.addRow('Назначение:',self.target);layout.addRow(choose)
        self.amounts=W.QTableWidget(len(assets),3);self.amounts.setHorizontalHeaderLabels(['Инвентарный номер','Переместить количество','Дополнение для отделяемой части'])
        self.amounts.horizontalHeader().setStretchLastSection(True)
        for n,a in enumerate(assets):
            for col,value in enumerate((a['number'],str(a.get('quantity',1)),'')):
                cell=W.QTableWidgetItem(value)
                if col==0:cell.setFlags(cell.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                self.amounts.setItem(n,col,cell)
        self.amounts.setMinimumHeight(110);layout.addRow(self.amounts)
        hint=W.QLabel('При переносе части количественной карточки введите количество и ручное дополнение новой карточки. Остаток останется на прежнем месте.')
        hint.setWordWrap(True);layout.addRow(hint)
        self.floor=W.QLineEdit();self.floor.setPlaceholderText('Этаж выбранного места: 1, 2, цоколь, технический')
        layout.addRow('Этаж:',self.floor)
        catalogs=client.api('/catalogs')
        self.responsible=ReferenceCombo(catalogs['responsibles'],'Сохранить текущего ответственного')
        self.supplier=ReferenceCombo(catalogs['suppliers'],'Сохранить текущего поставщика')
        self.date=W.QDateEdit(QtCore.QDate.currentDate());self.date.setCalendarPopup(True);self.date.setDisplayFormat('dd.MM.yyyy')
        self.number=W.QLineEdit();self.comment=W.QLineEdit()
        for label,field in [('Ответственное лицо:',self.responsible),('Поставщик:',self.supplier),('Дата документа:',self.date),('Номер документа:',self.number),('Комментарий:',self.comment)]:layout.addRow(label,field)
        self.error=W.QLabel();self.error.setWordWrap(True);self.error.setStyleSheet('color:#DC2626');layout.addRow(self.error)
        self.request=None
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok|W.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(W.QDialogButtonBox.StandardButton.Ok).setText('Провести');buttons.button(W.QDialogButtonBox.StandardButton.Cancel).setText('Отмена')
        buttons.accepted.connect(self.submit);buttons.rejected.connect(self.reject);layout.addRow(buttons)

    def choose(self):
        dialog=LocationDialog(self.client)
        if dialog.exec()!=W.QDialog.DialogCode.Accepted:return
        self.destination=dialog.ident
        rows=self.client.api('/locations');names={r['id']:r for r in rows};row=names[self.destination]
        self.target.setText((names[row['parent']]['name']+' / ' if row['parent'] else '')+row['name'])

    def submit(self):
        try:
            if not self.destination:raise ValueError('Выберите склад / подсклад назначения')
            selected=[]
            for n,a in enumerate(self.assets):
                amount=quantity(self.amounts.item(n,1).text(),positive=True);current=quantity(a.get('quantity',1))
                if amount>current:raise ValueError('Количество превышает остаток карточки '+a['number'])
                line={'id':a['id'],'version':a['version']}
                if amount<current:
                    suffix=self.amounts.item(n,2).text()
                    if not suffix.strip():raise ValueError('Введите дополнение для отделяемой части '+a['number'])
                    line.update(quantity=qnumber(amount),suffix=suffix)
                selected.append(line)
            p={'source':self.assets[0]['location'],'destination':self.destination,
               'assets':selected,
               'date':self.date.date().toString('yyyy-MM-dd'),'number':self.number.text(),'comment':self.comment.text(),'floor':self.floor.text()}
            responsible=self.responsible.selected_id();supplier=self.supplier.selected_id()
            if responsible is not None:p['responsible_id']=responsible
            if supplier is not None:p['supplier_id']=supplier
            if self.request is None:self.request=str(uuid.uuid4())
            p['request_id']=self.request
            self.client.api('/move',p);self.accept()
        except Exception as exc:self.error.setText(str(exc))
