import pytest
from fastapi.testclient import TestClient
from aho.server import create_app

PASSWORD='test-password-123'

def test_users_and_permissions(tmp_path):
    app=create_app(tmp_path);s=app.state.store;s.setup('ignored',PASSWORD)
    c=TestClient(app)
    def login(name,password=PASSWORD):
        return {'Authorization':'Bearer '+c.post('/login',json={'name':name,'password':password}).json()['token']}
    admin=login('Администратор')
    assert c.get('/me',headers=admin).json()['is_admin']
    p={'name':'Оператор','password':PASSWORD,'permissions':['labels'],'active':True}
    r=c.post('/users/save',headers=admin,json=p);assert r.status_code==200
    ident=r.json()['id'];operator=login('Оператор')
    assert c.get('/users',headers=operator).status_code==403
    assert c.post('/users/save',headers=operator,json=p).status_code==403
    assert c.post('/imports/inspect',headers=operator,json={}).status_code==403
    assert c.post('/move',headers=operator,json={'request_id':'00000000-0000-0000-0000-000000000001'}).status_code==403
    assert c.get('/assets',headers=operator).status_code==200
    assert c.post('/backup',headers=operator,json={}).status_code==403
    assert c.get('/audit',headers=operator).status_code==403
    r=c.post('/users/save',headers=admin,json=dict(p,id=ident,permissions=['backup']))
    assert r.status_code==200
    assert c.get('/me',headers=operator).status_code==403
    operator=login('Оператор');assert c.post('/backup',headers=operator,json={}).status_code==200
    assert c.post('/labels',headers=operator,json={}).status_code==403
    aid=c.get('/me',headers=admin).json()['id']
    assert c.post('/users/save',headers=admin,json={'id':aid,'name':'Другой','active':True,'permissions':[]}).status_code==400
    assert c.post('/users/save',headers=admin,json={'id':aid,'name':'Администратор','active':False,'permissions':[]}).status_code==400
    assert c.post('/users/save',headers=admin,json=dict(p,id=ident,active=False)).status_code==200
    assert c.post('/login',json={'name':'Оператор','password':PASSWORD}).status_code==400
    assert 'salt' not in c.get('/users',headers=admin).text
    assert c.post('/logout',headers=admin,json={}).status_code==200
    assert c.get('/me',headers=admin).status_code==403

def test_existing_admin_migration(tmp_path):
    import sqlite3,hashlib
    from aho.core import Store
    path=tmp_path/'inventory.sqlite3'
    salt='00'*16
    digest=hashlib.scrypt(PASSWORD.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE users(id TEXT PRIMARY KEY,name TEXT UNIQUE NOT NULL,salt TEXT NOT NULL,hash TEXT NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1)')
        db.execute('INSERT INTO users VALUES(?,?,?,?,?,1)',('old-admin','admin',salt,digest,'admin'))
    s=Store(tmp_path)
    u=s.user(s.login('Администратор',PASSWORD)['token'])
    assert u['id']=='old-admin' and u['is_admin']
    Store(tmp_path)
    assert s.read('SELECT count(*) AS n FROM users')[0]['n']==1

def test_user_dialog_fields():
    from PySide6 import QtWidgets as W
    from aho.user_dialog import UsersDialog,LoginDialog
    from aho.security import PERMISSIONS
    app=W.QApplication.instance() or W.QApplication([])
    class Mock(W.QWidget):
        def api(self,path):
            if path=='/login/users':return [{'name':'Администратор'}]
            return {'permissions':PERMISSIONS,'users':[{'id':'admin','name':'Администратор','active':True,'permissions':[]}]}
    client=Mock();dialog=UsersDialog(client)
    assert len(dialog.checks)==len(PERMISSIONS)
    dialog.select.setCurrentIndex(1)
    assert dialog.name.isReadOnly() and not dialog.active.isEnabled()
    assert all(cb.isChecked() and not cb.isEnabled() for cb in dialog.checks.values())
    login=LoginDialog(client);assert login.name.currentText()=='Администратор'
    dialog.close();login.close();client.close()
