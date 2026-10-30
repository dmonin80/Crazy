from collections import Counter
from PySide6 import QtCore, QtWidgets as W


class ReferenceCombo(W.QComboBox):
    """Searchable selection that never accepts an arbitrary typed value as an ID."""
    def __init__(self, entries, placeholder='Не выбрано', parent=None):
        super().__init__(parent)
        self.setMinimumContentsLength(28)
        self.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setEditable(True)
        self.setInsertPolicy(W.QComboBox.InsertPolicy.NoInsert)
        self.addItem(placeholder, None)
        active=[r for r in entries if not r.get('archived')]
        labels=[r['name']+(' — '+r.get('details','') if r.get('details') else '') for r in active]
        counts=Counter(labels)
        for row,label in zip(active,labels):
            if counts[label]>1:label+=' ['+row['id'][:8]+']'
            self.addItem(label,row['id'])
            self.setItemData(self.count()-1,row['id'],QtCore.Qt.ItemDataRole.ToolTipRole)
        self.completer().setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.completer().setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        self.completer().setCompletionMode(W.QCompleter.CompletionMode.PopupCompletion)

    def selected_id(self):
        text=self.currentText()
        index=self.currentIndex()
        if index>=0 and self.itemText(index)==text:
            return self.itemData(index)
        matches=[i for i in range(self.count()) if self.itemText(i)==text]
        if len(matches)==1:return self.itemData(matches[0])
        raise ValueError('Выберите существующую запись из списка. Новую запись сначала добавьте через «Справочники».')


class LocationDialog(W.QDialog):
    def __init__(self,client,allow_zero=True):
        super().__init__(client)
        self.setWindowTitle('Выбор склада / подсклада');self.resize(620,430)
        layout=W.QVBoxLayout(self)
        self.search=W.QLineEdit();self.search.setPlaceholderText('Поиск склада или подсклада');layout.addWidget(self.search)
        self.tree=W.QTreeWidget();self.tree.setHeaderLabels(['Склад / подсклад']);layout.addWidget(self.tree)
        rows=[r for r in client.api('/locations') if not r.get('archived') and (allow_zero or r['id']!='zero')]
        roots={}
        for row in rows:
            if row['parent'] is None:
                item=W.QTreeWidgetItem([row['name']]);item.setData(0,QtCore.Qt.ItemDataRole.UserRole,row['id']);item.setToolTip(0,row['name']+'\nID: '+row['id']);self.tree.addTopLevelItem(item);roots[row['id']]=item
        for row in rows:
            if row['parent'] in roots:
                item=W.QTreeWidgetItem([row['name']]);item.setData(0,QtCore.Qt.ItemDataRole.UserRole,row['id']);item.setToolTip(0,row['name']+'\nID: '+row['id']);roots[row['parent']].addChild(item)
        self.tree.expandAll()
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok|W.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(W.QDialogButtonBox.StandardButton.Ok).setText('Выбрать');buttons.button(W.QDialogButtonBox.StandardButton.Cancel).setText('Отмена')
        layout.addWidget(buttons);buttons.accepted.connect(self.choose);buttons.rejected.connect(self.reject)
        self.tree.itemDoubleClicked.connect(lambda *_:self.choose())
        self.search.textChanged.connect(self.filter_rows)
        self.ident=None

    def filter_rows(self,text):
        text=text.casefold()
        for n in range(self.tree.topLevelItemCount()):
            root=self.tree.topLevelItem(n);root_match=text in root.text(0).casefold();visible=root_match
            for m in range(root.childCount()):
                child=root.child(m);match=root_match or text in child.text(0).casefold();child.setHidden(not match);visible=visible or match
            root.setHidden(not visible)

    def choose(self):
        item=self.tree.currentItem()
        if item is None:return
        self.ident=item.data(0,QtCore.Qt.ItemDataRole.UserRole);self.accept()
