from PySide6 import QtWidgets as W

class LoginDialog(W.QDialog):
    def __init__(self,client):
        super().__init__(client);self.client=client;self.setWindowTitle('Выбор пользователя');self.setMinimumWidth(420)
        f=W.QFormLayout(self);self.name=W.QComboBox();self.name.addItems([u['name'] for u in client.api('/login/users')]);f.addRow('Пользователь',self.name)
        self.password=W.QLineEdit();self.password.setEchoMode(W.QLineEdit.EchoMode.Password);f.addRow('Пароль',self.password)
        self.error=W.QLabel();self.error.setWordWrap(True);f.addRow(self.error)
        b=W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok|W.QDialogButtonBox.StandardButton.Cancel);f.addRow(b);b.accepted.connect(self.submit);b.rejected.connect(self.reject)
    def submit(self):
        try:
            old=self.client.token
            result=self.client.api('/login',{'name':self.name.currentText(),'password':self.password.text()})
            if old:self.client.api('/logout',{})
            self.client.token=result['token'];self.client.current_user=self.client.api('/me');self.client.apply_permissions();self.client.sid=None;self.client.quick.setChecked(False);self.client.session_label.setText('Сессия не выбрана');self.client.refresh()
            self.client.statusBar().showMessage('Пользователь: '+self.name.currentText());self.password.clear();self.accept()
        except Exception as e:self.error.setText(str(e));self.password.clear()

class UsersDialog(W.QDialog):
    def __init__(self,client):
        super().__init__(client);self.client=client;self.setWindowTitle('Справочник пользователей и разрешений');self.resize(620,650)
        self.data=client.api('/users');self.ident=None
        f=W.QFormLayout(self);self.select=W.QComboBox();self.select.addItem('— Новый пользователь —',None)
        for u in self.data['users']:self.select.addItem(u['name'],u)
        f.addRow('Выберите',self.select);self.name=W.QLineEdit();f.addRow('Имя',self.name)
        self.password=W.QLineEdit();self.password.setEchoMode(W.QLineEdit.EchoMode.Password);self.password.setPlaceholderText('От 12 символов; пусто — сохранить пароль');f.addRow('Новый пароль',self.password)
        self.repeat=W.QLineEdit();self.repeat.setEchoMode(W.QLineEdit.EchoMode.Password);f.addRow('Повтор пароля',self.repeat)
        self.active=W.QCheckBox('Пользователь активен');self.active.setChecked(True);f.addRow(self.active)
        f.addRow(W.QLabel('Просмотр имущества доступен всем. Разрешённые действия:'))
        self.checks={}
        for key,label in self.data['permissions'].items():
            cb=W.QCheckBox(label);self.checks[key]=cb;f.addRow(cb)
        self.error=W.QLabel();self.error.setWordWrap(True);f.addRow(self.error)
        save=W.QPushButton('Сохранить пользователя');save.clicked.connect(self.save);f.addRow(save)
        close=W.QPushButton('Закрыть');close.clicked.connect(self.accept);f.addRow(close);self.select.currentIndexChanged.connect(self.load)
    def load(self):
        u=self.select.currentData() or {};self.ident=u.get('id');permanent=u.get('name')=='Администратор'
        self.name.setText(u.get('name',''));self.name.setReadOnly(permanent);self.active.setChecked(bool(u.get('active',True)));self.active.setEnabled(not permanent);self.password.clear();self.repeat.clear();self.error.clear()
        for k,cb in self.checks.items():cb.setChecked(permanent or k in u.get('permissions',[]));cb.setEnabled(not permanent)
    def save(self):
        try:
            if self.password.text()!=self.repeat.text():raise ValueError('Пароли не совпадают')
            self.client.api('/users/save',{'id':self.ident,'name':self.name.text(),'password':self.password.text(),'active':self.active.isChecked(),'permissions':[k for k,c in self.checks.items() if c.isChecked()]})
            self.password.clear();self.repeat.clear()
            W.QMessageBox.information(self,'Сохранено','Пользователь сохранён.' + (' Войдите заново с новым паролем.' if self.ident==self.client.current_user.get('id') else ''))
            self.accept()
        except Exception as e:self.error.setText(str(e))
