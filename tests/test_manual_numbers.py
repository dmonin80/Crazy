from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import pytest
from aho.core import Store,uid,Conflict


@pytest.fixture
def data(tmp_path):
    s=Store(tmp_path);s.setup('admin','manual-number-password');u=s.user(s.login('Администратор','manual-number-password')['token'])
    rows=[{'code':'0001','name':'Стул','unit':'шт','quantity':4,'rows':[2]}, {'code':'0001A','name':'Стол','unit':'шт','quantity':2,'rows':[3]}]
    s.mutate(u,uid(),'import',{},lambda c:s.import_rows(c,rows,'hash','test.xlsx'))
    loc=s.mutate(u,uid(),'loc',{},lambda c:s.add_location(c,{'name':'Склад'}))['id']
    return s,u,loc


def allocate(data,suffixes,count=1,code='0001'):
    s,u,loc=data
    item=next(r for r in s.stock() if r['code']==code)
    p={'item_id':item['id'],'quantity':count,'destination':loc,'date':'2026-10-29'}
    if suffixes is not None:p['suffixes']=suffixes
    return s.mutate(u,uid(),'allocate',p,lambda c:s.movement(c,u['id'],p,True))


@pytest.mark.parametrize('suffixes',[None,[],[''],[' '],['-1','-2'],['-x '],['\t1']])
def test_no_automatic_numbers_or_invalid_additions(data,suffixes):
    with pytest.raises(ValueError):allocate(data,suffixes)
    s,_,_=data
    assert not s.assets() and not s.read('SELECT * FROM documents')
    assert next(r for r in s.stock() if r['code']=='0001')['unassigned']==4


@pytest.mark.parametrize('addition',['-1','/А-01','А','_0001'])
def test_exact_user_addition_and_no_implicit_separator(data,addition):
    allocate(data,[addition]);s,_,_=data
    a=s.assets()[0]
    assert a['number']=='0001'+addition and a['suffix']==addition and a['code']=='0001'


def test_conflicts_in_batch_and_between_codes(data):
    with pytest.raises(Conflict):allocate(data,['-X','-X'],2)
    allocate(data,['A1'])
    with pytest.raises(Conflict):allocate(data,['A1'])
    # Different item codes can still produce the same full number.
    with pytest.raises(Conflict):allocate(data,['1'],code='0001A')
    s,_,_=data;assert len(s.assets())==1
    assert next(r for r in s.stock() if r['code']=='0001A')['unassigned']==2


def test_concurrent_same_manual_number(data):
    def run(_):
        try:allocate(data,['-ONE']);return True
        except Conflict:return False
    with ThreadPoolExecutor(2) as pool:assert sorted(pool.map(run,range(2)))==[False,True]
    s,_,_=data;assert len(s.assets())==1 and s.assets()[0]['number']=='0001-ONE'


def test_gui_manual_number_prompt_and_large_navigation(tmp_path):
    project=Path(__file__).resolve().parents[1]
    script=r'''
import sys
from pathlib import Path
from PySide6 import QtCore,QtWidgets as W
from fastapi.testclient import TestClient
from aho.core import uid
from aho.server import create_app
from aho.client import Client
from aho.stock_dialog import StockMoveDialog
app=W.QApplication([]);root=Path(sys.argv[1]);server=create_app(root/'data');s=server.state.store
s.setup('admin','manual-test-password');token=s.login('Администратор','manual-test-password')['token'];u=s.user(token)
s.mutate(u,uid(),'import',{},lambda c:s.import_rows(c,[{'code':'0001','name':'Стул','unit':'шт','quantity':4,'rows':[2]}],'hash','test.xlsx'))
loc=s.mutate(u,uid(),'loc',{},lambda c:s.add_location(c,{'name':'Основной склад'}))['id']
http=TestClient(server)
class Window(Client):
    def api(self,path,payload=None):
        h={'Authorization':'Bearer '+self.token}
        r=http.get(path,headers=h) if payload is None else http.post(path,headers=h,json=payload)
        if r.is_error:raise RuntimeError(str(r.json().get('detail')))
        return r.json()
w=Window(local_url='http://127.0.0.1:8765',settings_root=root);w.token=token;w.refresh();w.show();app.processEvents()
buttons=w.findChildren(W.QPushButton)
zero=[b for b in buttons if b.text()=='Нулевой склад'];assets=[b for b in buttons if b.text()=='Имущество по складам']
assert len(zero)==1 and len(assets)==1
move=next(b for b in buttons if b.text()=='Переместить')
assert zero[0].height()>=58 and assets[0].height()>=58
assert zero[0].mapTo(w,QtCore.QPoint()).y()<move.mapTo(w,QtCore.QPoint()).y()
assets[0].click();assert w.view_tabs.currentIndex()==1 and assets[0].isChecked()
zero[0].click();assert w.view_tabs.currentIndex()==0 and zero[0].isChecked()
w.grab().save(str(root/'large_navigation.png'))
d=StockMoveDialog(w,s.stock()[0]);d.warehouse.setCurrentIndex(d.warehouse.findData(loc))
assert d.suffix_table.item(0,0).text()==''
d.submit();assert d.pending is None and not s.assets() and 'дополнение' in d.error.text()
d.quantity.setValue(2);assert d.suffix_table.item(1,0).text()==''
d.suffix_table.item(0,0).setText('-X');d.suffix_table.item(1,0).setText('/Y')
assert d.suffix_table.item(0,1).text()=='0001-X' and d.suffix_table.item(1,1).text()=='0001/Y'
d.grab().save(str(root/'manual_numbers.png'))
d.submit();assert d.result is not None,d.error.text()
assert {a['number'] for a in s.assets()}=={'0001-X','0001/Y'}
assert s.stock()[0]['unassigned']==2
w.close();print('MANUAL_NUMBERS_AND_NAVIGATION_OK')
'''
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],cwd=project,env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=25)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'MANUAL_NUMBERS_AND_NAVIGATION_OK' in result.stdout
