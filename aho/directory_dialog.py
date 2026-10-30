"""Business directories; all writes go through the authenticated server."""
from PySide6 import QtCore, QtWidgets as W
from .reference_widgets import ReferenceCombo

TABS=[('warehouses','Склады'),('rooms','Подсклады / кабинеты'),('responsibles','Ответственные лица'),('suppliers','Поставщики'),('units','Единицы измерения (1С)')]


class DirectoryEditor(W.QDialog):
    def __init__(self,owner,kind,record=None):
        super().__init__(owner)
        self.owner=owner;self.kind=kind;self.record=record;self.saved=False
        self.setWindowTitle(('Изменить' if record else 'Добавить')+' — '+dict(TABS)[kind]);self.resize(620,240)
        form=W.QFormLayout(self)
        self.name=W.QLineEdit(record['name'] if record else '')
        form.addRow('ФИО:' if kind=='responsibles' else 'Наименование:',self.name)
        self.details=W.QLineEdit(record.get('details','') if record else '')
        self.parent=None
        if kind in ('responsibles','suppliers'):
            form.addRow('Подразделение:' if kind=='responsibles' else 'ИНН / реквизиты:',self.details)
        if kind=='rooms':
            roots=[r for r in owner.data['locations'] if r['parent'] is None and r['id']!='zero']
            self.parent=ReferenceCombo(roots,'— выберите основной склад —')
            if record:self.parent.setCurrentIndex(self.parent.findData(record['parent']));self.parent.setEnabled(False)
            form.addRow('Основной склад:',self.parent)
        self.error=W.QLabel();self.error.setWordWrap(True);self.error.setStyleSheet('color:#ae2020');form.addRow(self.error)
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Save|W.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(W.QDialogButtonBox.StandardButton.Save).setText('Сохранить');buttons.button(W.QDialogButtonBox.StandardButton.Cancel).setText('Отмена')
        form.addRow(buttons);buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject)

    def save(self):
        try:
            name=self.name.text().strip()
            if not name:raise ValueError('Заполните наименование / ФИО')
            parent=self.parent.selected_id() if self.parent else None
            if self.kind=='rooms' and not parent:raise ValueError('Выберите основной склад')
            payload={'name':name,'details':self.details.text()}
            if self.kind in ('warehouses','rooms'):payload['parent']=parent
            kind='locations' if self.kind in ('warehouses','rooms') else self.kind
            matches=[r for r in self.owner.data[kind] if r['name'].strip().casefold()==name.casefold() and (self.record is None or r['id']!=self.record['id']) and (kind!='locations' or r['parent']==parent)]
            if matches:
                if W.QMessageBox.question(self,'Похожие записи','Записи с таким именем уже существуют. Проверьте их подразделение или реквизиты. Сохранить отдельную запись?')!=W.QMessageBox.StandardButton.Yes:return
                payload['confirm_duplicate']=True
            path='/catalogs/'+kind
            if self.record:
                path+='/'+self.record['id'];payload.update(version=self.record['version'],action='edit')
            self.owner.client.command(path,payload)
            self.saved=True;self.accept()
        except Exception as exc:self.error.setText(str(exc))


class DirectoriesDialog(W.QDialog):
    def __init__(self,client):
        super().__init__(client);self.client=client;self.data={};self.admin=client.api('/me')['role']=='admin'
        self.setWindowTitle('Справочники');self.resize(1080,660)
        layout=W.QVBoxLayout(self)
        title=W.QLabel('Справочники учёта');title.setStyleSheet('font-size:20px;font-weight:600;color:#17436b');layout.addWidget(title)
        hint=W.QLabel('Заполните справочники заранее. Архивные записи сохраняют историю и не предлагаются для новых назначений. Единицы измерения поступают только из 1С.')
        hint.setWordWrap(True);layout.addWidget(hint)
        bar=W.QHBoxLayout();layout.addLayout(bar)
        self.search=W.QLineEdit();self.search.setPlaceholderText('Поиск в выбранном справочнике');bar.addWidget(self.search)
        self.archived=W.QCheckBox('Показывать архивные');bar.addWidget(self.archived)
        self.tabs=W.QTabWidget();layout.addWidget(self.tabs,1);self.tables={}
        for kind,label in TABS:
            table=W.QTableWidget();table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows);table.setSelectionMode(W.QAbstractItemView.SelectionMode.SingleSelection)
            table.setAlternatingRowColors(True);table.horizontalHeader().setStretchLastSection(True)
            table.itemSelectionChanged.connect(self.update_buttons)
            self.tables[kind]=table;self.tabs.addTab(table,label)
        buttons=W.QHBoxLayout();layout.addLayout(buttons)
        self.add_button=W.QPushButton('Добавить');self.edit_button=W.QPushButton('Изменить')
        self.archive_button=W.QPushButton('В архив');self.restore_button=W.QPushButton('Восстановить')
        refresh=W.QPushButton('Обновить');close=W.QPushButton('Закрыть')
        for button in (self.add_button,self.edit_button,self.archive_button,self.restore_button,refresh,close):buttons.addWidget(button)
        self.add_button.clicked.connect(lambda:self.safe(lambda:self.edit(False)))
        self.edit_button.clicked.connect(lambda:self.safe(lambda:self.edit(True)))
        self.archive_button.clicked.connect(lambda:self.safe(lambda:self.change_state('archive')))
        self.restore_button.clicked.connect(lambda:self.safe(lambda:self.change_state('restore')))
        refresh.clicked.connect(lambda:self.safe(self.reload));close.clicked.connect(self.accept)
        self.search.textChanged.connect(lambda _:self.populate());self.archived.toggled.connect(lambda _:self.populate())
        self.tabs.currentChanged.connect(lambda _:self.populate())
        self.error=W.QLabel();self.error.setWordWrap(True);self.error.setStyleSheet('color:#ae2020');layout.addWidget(self.error)
        self.reload()

    def safe(self,fn):
        try:self.error.clear();fn()
        except Exception as exc:self.error.setText(str(exc))

    def kind(self):return TABS[self.tabs.currentIndex()][0]

    def selected(self):
        table=self.tables[self.kind()];row=table.currentRow()
        if row<0 or table.item(row,0) is None:return None
        ident=table.item(row,0).data(QtCore.Qt.ItemDataRole.UserRole)
        source='locations' if self.kind() in ('warehouses','rooms') else self.kind()
        return next((r for r in self.data.get(source,[]) if isinstance(r,dict) and r['id']==ident),None)

    def reload(self):
        self.data=self.client.api('/catalogs');self.populate()

    def populate(self):
        if not self.data:return
        kind=self.kind();table=self.tables[kind];query=self.search.text().casefold()
        if kind=='units':
            rows=[{'id':str(i),'name':name} for i,name in enumerate(self.data['units'])]
            columns=[('name','Единица измерения — исходное значение 1С')]
        else:
            source='locations' if kind in ('warehouses','rooms') else kind
            rows=self.data[source]
            if kind=='warehouses':rows=[r for r in rows if r['parent'] is None]
            elif kind=='rooms':rows=[r for r in rows if r['parent'] is not None]
            rows=[r for r in rows if self.archived.isChecked() or not r.get('archived')]
            names={r['id']:r['name'] for r in self.data['locations']}
            rows=[dict(r,parent_name=names.get(r.get('parent'),''),state='Архив' if r.get('archived') else 'Активна',short_id=r['id'][:8]) for r in rows]
            columns=[('name','ФИО' if kind=='responsibles' else 'Наименование')]
            if kind=='rooms':columns.append(('parent_name','Основной склад'))
            if kind in ('responsibles','suppliers'):columns.append(('details','Подразделение' if kind=='responsibles' else 'ИНН / реквизиты'))
            columns += [('state','Состояние'),('short_id','ID')]
        rows=[r for r in rows if query in ' '.join(str(v) for v in r.values()).casefold()]
        table.setRowCount(len(rows));table.setColumnCount(len(columns));table.setHorizontalHeaderLabels([label for _,label in columns])
        for n,row in enumerate(rows):
            for col,(key,_) in enumerate(columns):
                item=W.QTableWidgetItem(str(row.get(key,'')));item.setData(QtCore.Qt.ItemDataRole.UserRole,row['id']);item.setToolTip(str(row.get(key,''))+'\nID: '+row['id']);table.setItem(n,col,item)
        table.resizeColumnsToContents()
        for col in range(len(columns)):table.setColumnWidth(col,min(430,max(140,table.columnWidth(col))))
        self.update_buttons()

    def update_buttons(self):
        if not hasattr(self,'add_button'):return
        row=self.selected();mutable=self.admin and self.kind()!='units'
        system=bool(row and row['id']=='zero');active=bool(row and not row.get('archived'))
        self.add_button.setEnabled(mutable);self.edit_button.setEnabled(mutable and active and not system)
        self.archive_button.setEnabled(mutable and active and not system);self.restore_button.setEnabled(mutable and bool(row) and not active and not system)

    def edit(self,existing):
        if not self.admin or self.kind()=='units':return
        record=self.selected() if existing else None
        if existing and record is None:raise ValueError('Выберите запись')
        editor=DirectoryEditor(self,self.kind(),record)
        if editor.exec()==W.QDialog.DialogCode.Accepted:self.reload()

    def change_state(self,action):
        row=self.selected()
        if row is None:raise ValueError('Выберите запись')
        prompt='Перевести запись в архив?' if action=='archive' else 'Восстановить запись из архива?'
        if W.QMessageBox.question(self,'Справочник',prompt)!=W.QMessageBox.StandardButton.Yes:return
        kind='locations' if self.kind() in ('warehouses','rooms') else self.kind()
        self.client.command('/catalogs/'+kind+'/'+row['id'],{'action':action,'version':row['version']})
        self.reload()
