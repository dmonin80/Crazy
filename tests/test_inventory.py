from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import BytesIO
import base64
import json
import sqlite3
import uuid
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from aho.core import Store,Conflict
from aho.importer import preview
from aho.server import create_app

MAP={'name':0,'code':1,'unit':2,'quantity':3}

def rid():return str(uuid.uuid4())

def xlsx(quantity=10):
    wb=Workbook();ws=wb.active;ws.append(['Выгрузка из 1С']);ws.append(['Номенклатура','Код','Ед. изм.','Количество']);ws.append(['  Стул офисный  ',123,'шт',quantity]);ws['B3'].number_format='000000';out=BytesIO();wb.save(out);return out.getvalue()

@pytest.fixture
def data(tmp_path):
    s=Store(tmp_path);s.setup('admin','test-password-123');u=s.user(s.login('Администратор','test-password-123')['token'])
    parsed=preview(xlsx(),'a.xlsx',MAP,2)
    s.mutate(u,rid(),'import',{},lambda c:s.import_rows(c,parsed['rows'],parsed['hash'],'a.xlsx'))
    loc=s.mutate(u,rid(),'location',{},lambda c:s.add_location(c,{'name':'Офис'}))['id']
    return s,u,loc

def allocate(s,u,loc,count=1,request=None):
    p={'item_id':s.stock()[0]['id'],'quantity':count,'suffixes':[f'/{n+1:04d}' for n in range(count)],'destination':loc,'date':str(date.today()),'number':'0001'}
    return s.mutate(u,request or rid(),'allocate',p,lambda c:s.movement(c,u['id'],p,True))

def test_import_exact_and_zeroes():
    p=preview(xlsx(),'a.xlsx',MAP,2)
    assert not p['errors'];assert p['rows'][0]['code']=='000123';assert p['rows'][0]['name']=='  Стул офисный  '

@pytest.mark.parametrize('q',[-1,'NaN','abc'])
def test_invalid_quantity(q):assert preview(xlsx(q),'a.xlsx',MAP,2)['errors']

def test_duplicate_requires_confirmation():
    raw='name;code;unit;quantity\na;01;шт;2\na;01;шт;3'.encode()
    assert preview(raw,'a.csv',MAP)['errors']
    assert preview(raw,'a.csv',MAP,merge=True)['units']==5
    assert preview(raw.replace(b'a;01;\xd1\x88\xd1\x82;3',b'b;01;\xd1\x88\xd1\x82;3'),'a.csv',MAP,merge=True)['errors']

def test_first_import_only(data):
    s,u,loc=data
    with pytest.raises(Conflict):s.mutate(u,rid(),'import2',{},lambda c:s.import_rows(c,[],'different','a.xlsx'))
    assert s.stock()[0]['initial']==10

def test_concurrent_stock(data):
    s,u,loc=data
    def run(_):
        try:allocate(s,u,loc,7);return True
        except Conflict:return False
    with ThreadPoolExecutor(2) as pool:assert sorted(pool.map(run,range(2)))==[False,True]
    assert s.stock()[0]['unassigned']==3;assert len({r['number'] for r in s.assets()})==7

def test_idempotency(data):
    s,u,loc=data;request=rid();a=allocate(s,u,loc,2,request);b=allocate(s,u,loc,2,request)
    assert a==b;assert len(s.assets())==2
    with pytest.raises(Conflict):allocate(s,u,loc,3,request)

def test_return_and_reissue(data):
    s,u,loc=data;allocate(s,u,loc);a=s.assets()[0]
    def move(source,dest,version):
        p={'source':source,'destination':dest,'assets':[{'id':a['id'],'version':version}],'date':'2026-10-29'}
        return s.mutate(u,rid(),'move',p,lambda c:s.movement(c,u['id'],p))
    move(loc,'zero',1);assert s.stock()[0]['returned']==1
    move('zero',loc,2);assert s.assets()[0]['number']==a['number'];assert len(s.assets())==1
    with pytest.raises(Conflict):move(loc,'zero',1)
    assert len(s.read('SELECT * FROM documents'))==3

def test_snapshot_and_double_scan(data):
    s,u,loc=data;allocate(s,u,loc);a=s.assets()[0]
    sid=s.mutate(u,rid(),'start',{},lambda c:s.start_session(c,{'name':'Проверка','location':loc}))['id']
    p={'asset_id':a['id'],'version':1,'status':'В наличии','actual':loc,'fast':True}
    s.mutate(u,rid(),'check',p,lambda c:s.check(c,u['id'],sid,p))
    with pytest.raises(Conflict):s.mutate(u,rid(),'check',p,lambda c:s.check(c,u['id'],sid,p))
    assert len(s.read('SELECT * FROM checks'))==1
    with s.transaction() as c:c.execute("UPDATE sessions SET state='Завершена' WHERE id=?",(sid,))
    p['version']=2
    with pytest.raises(Conflict):s.mutate(u,rid(),'check',p,lambda c:s.check(c,u['id'],sid,p))

def test_movement_after_snapshot(data):
    s,u,loc=data;allocate(s,u,loc);a=s.assets()[0]
    sid=s.mutate(u,rid(),'start',{},lambda c:s.start_session(c,{'name':'Проверка','location':loc}))['id']
    p={'source':loc,'destination':'zero','assets':[{'id':a['id'],'version':1}],'date':'2026-10-29'}
    s.mutate(u,rid(),'move',p,lambda c:s.movement(c,u['id'],p))
    check={'asset_id':a['id'],'version':1,'status':'В наличии','actual':loc,'fast':True}
    with pytest.raises(Conflict):s.mutate(u,rid(),'check',check,lambda c:s.check(c,u['id'],sid,check))
    assert json.loads(s.read('SELECT snapshot FROM checks')[0]['snapshot'])['location']==loc

def test_qr_backup_restore(data,tmp_path):
    s,u,loc=data;allocate(s,u,loc);a=s.assets()[0];db=s.read("SELECT value FROM meta WHERE key='database_uuid'")[0]['value']
    qr=f"INV1:{db}:{a['id']}";assert s.resolve(qr)['id']==a['id']
    with pytest.raises(Conflict):s.resolve(f"INV1:{uuid.uuid4()}:{a['id']}")
    backup=s.backup();restored=Store(tmp_path/'restored')
    with sqlite3.connect(backup) as source,restored.connect() as target:source.backup(target)
    assert restored.resolve(qr)['number']==a['number']

def test_rights_and_api(tmp_path):
    app=create_app(tmp_path);s=app.state.store;s.setup('admin','test-password-123')
    with TestClient(app) as client:
        assert client.get('/stock').status_code==403
        token=client.post('/login',json={'name':'Администратор','password':'test-password-123'}).json()['token'];h={'Authorization':'Bearer '+token}
        assert client.get('/stock',headers=h).status_code==200
        from aho.security import save_user
        save_user(s,s.user(token),{'name':'Читатель','password':'test-password-123','permissions':[]})
        token=s.login('Читатель','test-password-123')['token'];h={'Authorization':'Bearer '+token}
        assert client.post('/locations',headers=h,json={'request_id':rid(),'name':'test'}).status_code==403

def test_pdf_size(data):
    from aho.labels import make_pdf
    import pymupdf
    s,u,loc=data;allocate(s,u,loc,2);pdf=make_pdf(s.assets(),rid())
    doc=pymupdf.open(stream=pdf,filetype='pdf');assert len(doc)==2
    assert abs(doc[0].rect.width-58*72/25.4)<0.01
    assert abs(doc[0].rect.height-40*72/25.4)<0.01

def test_pdf_qr_machine_decode(data):
    from aho.labels import make_pdf
    import pymupdf
    import zxingcpp
    from PIL import Image
    s,u,loc=data;allocate(s,u,loc);a=s.assets()[0];db=s.read("SELECT value FROM meta WHERE key='database_uuid'")[0]['value']
    for template in ('40x30','58x40','A4'):
        pdf=make_pdf([a],db,template,skip=3 if template=='A4' else 0)
        doc=pymupdf.open(stream=pdf,filetype='pdf');pix=doc[0].get_pixmap(dpi=300)
        image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        result=zxingcpp.read_barcodes(image)
        assert [r.text for r in result]==[f"INV1:{db}:{a['id']}"]

def test_api_import_retry_and_finding(tmp_path):
    app=create_app(tmp_path);app.state.store.setup('admin','test-password-123')
    with TestClient(app) as client:
        token=client.post('/login',json={'name':'Администратор','password':'test-password-123'}).json()['token'];h={'Authorization':'Bearer '+token}
        p={'data':base64.b64encode(xlsx()).decode(),'filename':'test.xlsx','header':2,'mapping':MAP,'request_id':rid()}
        first=client.post('/imports/commit',headers=h,json=p)
        assert first.status_code==200,first.text
        assert client.post('/imports/commit',headers=h,json=p).json()==first.json()
        assert client.post('/imports/compare',headers=h,json=p).json()['same_file']
        p['request_id']=rid();assert client.post('/imports/commit',headers=h,json=p).status_code==409
        sid=client.post('/sessions',headers=h,json={'request_id':rid(),'name':'Проверка'}).json()['id']
        response=client.post('/sessions/'+sid+'/finding',headers=h,json={'request_id':rid(),'description':'Неопознанный стул в кабинете 1'})
        assert response.status_code==200
        assert client.get('/stock',headers=h).json()[0]['unassigned']==10
