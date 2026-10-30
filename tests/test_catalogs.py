import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from aho.core import Store,Conflict,uid
from aho.catalogs import create_entry,update_entry
from aho.server import create_app

@pytest.fixture
def data(tmp_path):
    s=Store(tmp_path);s.setup('admin','catalog-test-password');u=s.user(s.login('Администратор','catalog-test-password')['token'])
    return s,u

def cmd(s,u,kind,p,ident=None):
    return s.mutate(u,uid(),'catalog.'+kind,p,lambda c:update_entry(c,kind,ident,p) if ident else (s.add_location(c,p) if kind=='locations' else create_entry(c,kind,p)),True)

def stock(s,u):
    s.mutate(u,uid(),'import',{},lambda c:s.import_rows(c,[{'code':'0001','name':'Стул','unit':'шт','quantity':3,'rows':[2]}],'hash','test.xlsx'))

def allocate(s,u,loc,**refs):
    p=dict(item_id=s.stock()[0]['id'],quantity=1,suffixes=['/ТЕСТ-'+str(len(s.assets())+1)],destination=loc,date='2026-10-29',**refs)
    return s.mutate(u,uid(),'allocate',p,lambda c:s.movement(c,u['id'],p,True))

def test_duplicate_ids_versions_and_audit(data):
    s,u=data
    first=cmd(s,u,'responsibles',{'name':'Иванов И.И.','details':'Отдел 1'})['id']
    with pytest.raises(Conflict):cmd(s,u,'responsibles',{'name':'иванов и.и.','details':'Отдел 2'})
    second=cmd(s,u,'responsibles',{'name':'Иванов И.И.','details':'Отдел 2','confirm_duplicate':True})['id']
    assert first!=second
    result=cmd(s,u,'responsibles',{'name':'Иванов Иван','details':'Отдел 1','version':1},first)
    assert result['version']==2
    with pytest.raises(Conflict):cmd(s,u,'responsibles',{'name':'Устаревшая правка','version':1},first)
    audit=json.loads(s.read("SELECT data FROM audit WHERE action='catalog.responsibles' ORDER BY at DESC")[0]['data'])
    assert audit['before']['name']=='Иванов И.И.' and audit['after']['name']=='Иванов Иван'

def test_assignments_archiving_rename_and_snapshots(data):
    s,u=data;stock(s,u)
    loc=cmd(s,u,'locations',{'name':'Здание'})['id']
    person=cmd(s,u,'responsibles',{'name':'Ответственный','details':'Отдел'})['id']
    supplier=cmd(s,u,'suppliers',{'name':'Поставщик','details':'ИНН тест'})['id']
    allocate(s,u,loc,responsible_id=person,supplier_id=supplier)
    asset=s.assets()[0];history=s.read('SELECT after_json FROM lines')[0]['after_json']
    sid=s.mutate(u,uid(),'session',{},lambda c:s.start_session(c,{'name':'Проверка'}))['id']
    cmd(s,u,'responsibles',{'name':'Новое ФИО','details':'Другой отдел','version':1},person)
    cmd(s,u,'locations',{'name':'Новое название','version':1},loc)
    assert s.assets()[0]['responsible']=='Новое ФИО' and s.assets()[0]['supplier']=='Поставщик'
    assert s.assets()[0]['location_name']=='Новое название'
    assert s.read('SELECT after_json FROM lines')[0]['after_json']==history
    snap=json.loads(s.read('SELECT snapshot FROM checks WHERE session_id=?',(sid,))[0]['snapshot'])
    assert snap['responsible']=='Ответственный' and snap['location_name']=='Здание'
    cmd(s,u,'responsibles',{'action':'archive','version':2},person)
    with pytest.raises(ValueError):allocate(s,u,loc,responsible_id=person)
    assert len(s.assets())==1
    p={'source':loc,'destination':'zero','assets':[{'id':asset['id'],'version':asset['version']}],'date':'2026-10-29'}
    s.mutate(u,uid(),'move',p,lambda c:s.movement(c,u['id'],p))
    assert s.assets()[0]['responsible_id']==person and s.assets()[0]['supplier_id']==supplier
    cmd(s,u,'responsibles',{'action':'restore','version':3},person)
    allocate(s,u,loc,responsible_id=person,supplier_id=supplier)

def test_unknown_archived_and_ambiguous_choices_blocked(data):
    s,u=data;stock(s,u);loc=cmd(s,u,'locations',{'name':'Склад'})['id']
    with pytest.raises(ValueError):allocate(s,u,loc,responsible='Вне справочника')
    with pytest.raises(ValueError):allocate(s,u,loc,supplier_id=uid())
    cmd(s,u,'responsibles',{'name':'Совпадающее ФИО'})
    cmd(s,u,'responsibles',{'name':'Совпадающее ФИО','details':'Другой отдел','confirm_duplicate':True})
    with pytest.raises(ValueError):allocate(s,u,loc,responsible='Совпадающее ФИО')
    assert s.stock()[0]['unassigned']==3 and not s.read('SELECT * FROM documents')

def test_location_rules(data):
    s,u=data
    parent=cmd(s,u,'locations',{'name':'Склад'})['id'];child=cmd(s,u,'locations',{'name':'101','parent':parent})['id']
    with pytest.raises(ValueError):cmd(s,u,'locations',{'action':'archive','version':1},'zero')
    with pytest.raises(Conflict):cmd(s,u,'locations',{'action':'archive','version':1},parent)
    cmd(s,u,'locations',{'action':'archive','version':1},child);cmd(s,u,'locations',{'action':'archive','version':1},parent)
    with pytest.raises(Conflict):cmd(s,u,'locations',{'action':'restore','version':2},child)
    cmd(s,u,'locations',{'action':'restore','version':2},parent);cmd(s,u,'locations',{'action':'restore','version':2},child)
    stock(s,u);allocate(s,u,child)
    with pytest.raises(Conflict):cmd(s,u,'locations',{'action':'archive','version':3},child)
    with pytest.raises(ValueError):cmd(s,u,'locations',{'name':'101','parent':None,'version':3},child)

def test_server_rights_and_idempotency(tmp_path):
    app=create_app(tmp_path);s=app.state.store;s.setup('admin','catalog-test-password')
    with TestClient(app) as c:
        token=c.post('/login',json={'name':'Администратор','password':'catalog-test-password'}).json()['token'];h={'Authorization':'Bearer '+token}
        assert c.get('/catalogs').status_code==403
        p={'request_id':uid(),'name':'Организация','details':'ИНН 123'}
        first=c.post('/catalogs/suppliers',headers=h,json=p)
        assert first.status_code==200 and c.post('/catalogs/suppliers',headers=h,json=p).json()==first.json()
        assert len(c.get('/catalogs',headers=h).json()['suppliers'])==1
        from aho.security import save_user
        for name in ('Оператор','Читатель'):
            save_user(s,s.user(token),{'name':name,'password':'catalog-test-password','permissions':[]})
            other={'Authorization':'Bearer '+s.login(name,'catalog-test-password')['token']}
            assert c.get('/catalogs',headers=other).status_code==200
            assert c.post('/catalogs/responsibles',headers=other,json={'request_id':uid(),'name':'Нет прав'}).status_code==403
        assert c.post('/catalogs/units',headers=h,json={'request_id':uid(),'name':'Чужая единица'}).status_code==400

def test_v1_migration_and_backup(tmp_path):
    path=tmp_path/'inventory.sqlite3';db_uuid=uid();aid=uid();iid=uid();import_id=uid()
    with sqlite3.connect(path) as c:
        c.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE locations(id TEXT PRIMARY KEY,name TEXT NOT NULL,parent TEXT,archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE imports(id TEXT PRIMARY KEY,hash TEXT UNIQUE NOT NULL,name TEXT NOT NULL,at TEXT NOT NULL);
CREATE TABLE items(id TEXT PRIMARY KEY,code TEXT UNIQUE NOT NULL,name TEXT NOT NULL,unit TEXT NOT NULL,initial INTEGER NOT NULL,import_id TEXT NOT NULL,source_rows TEXT NOT NULL);
CREATE TABLE assets(id TEXT PRIMARY KEY,item_id TEXT NOT NULL,suffix TEXT NOT NULL,number TEXT UNIQUE NOT NULL,location TEXT NOT NULL,responsible TEXT NOT NULL DEFAULT '',floor TEXT NOT NULL DEFAULT '',note TEXT NOT NULL DEFAULT '',version INTEGER NOT NULL DEFAULT 1);''')
        c.executemany('INSERT INTO meta VALUES(?,?)',[('database_uuid',db_uuid),('schema_version','1')])
        c.execute("INSERT INTO locations(id,name) VALUES('zero','Нулевой склад')")
        c.execute('INSERT INTO imports VALUES(?,?,?,?)',(import_id,'legacy','legacy.xlsx','2026-01-01'))
        c.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?)',(iid,'0001','Стул','шт',3,import_id,'[2]'))
        c.execute('INSERT INTO assets(id,item_id,suffix,number,location,responsible) VALUES(?,?,?,?,?,?)',(aid,iid,'0001','0001/0001','zero','  Старое ФИО  '))
    s=Store(tmp_path)
    assert s.read("SELECT value FROM meta WHERE key='schema_version'")[0]['value']=='3'
    assert s.assets()[0]['id']==aid and s.assets()[0]['number']=='0001/0001'
    assert s.assets()[0]['responsible']=='  Старое ФИО  ' and s.assets()[0]['responsible_id']
    assert s.resolve(f'INV1:{db_uuid}:{aid}')['id']==aid
    assert s.stock()[0]['unassigned']==2 and s.stock()[0]['returned']==1
    backups=list((tmp_path/'backups').glob('*.sqlite3'));assert len(backups)==1
    with sqlite3.connect(backups[0]) as c:assert c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]=='1'
    Store(tmp_path);assert len(list((tmp_path/'backups').glob('*.sqlite3')))==1
    assert len(s.read('SELECT * FROM responsibles'))==1
    with s.connect() as c:assert not c.execute('PRAGMA foreign_key_check').fetchall()
