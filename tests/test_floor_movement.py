import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from aho.core import Store,uid


@pytest.fixture
def prepared(tmp_path):
    s=Store(tmp_path);s.setup('admin','floor-test-password');u=s.user(s.login('Администратор','floor-test-password')['token'])
    s.mutate(u,uid(),'import',{},lambda c:s.import_rows(c,[{'code':'0001','name':'Стул','unit':'шт','quantity':3,'rows':[2]}],'testhash','test.xlsx'))
    def loc(name,parent=None):return s.mutate(u,uid(),'location',{},lambda c:s.add_location(c,{'name':name,'parent':parent}))['id']
    building=loc('Здание');first=loc('101',building);second=loc('201',building)
    p={'item_id':s.stock()[0]['id'],'quantity':2,'suffixes':['/0001','/0002'],'destination':first,'date':'2026-10-29','floor':'1'}
    s.mutate(u,uid(),'allocate',p,lambda c:s.movement(c,u['id'],p,True))
    return s,u,first,second


def test_group_move_updates_floor_and_history(prepared):
    s,u,first,second=prepared;before=s.assets();numbers={a['id']:a['number'] for a in before}
    p={'source':first,'destination':second,'assets':[{'id':a['id'],'version':a['version']} for a in before],'date':'2026-10-29','floor':'цоколь'}
    result=s.mutate(u,uid(),'move',p,lambda c:s.movement(c,u['id'],p))
    assert all(a['floor']=='цоколь' and a['location']==second and a['number']==numbers[a['id']] for a in s.assets())
    lines=s.read('SELECT * FROM lines WHERE document_id=?',(result['document_id'],))
    assert len(lines)==2
    assert all(json.loads(r['before_json'])['floor']=='1' and json.loads(r['after_json'])['floor']=='цоколь' for r in lines)
    assert s.stock()[0]['unassigned']==1


def test_omitted_floor_preserves_and_explicit_blank_clears(prepared):
    s,u,first,second=prepared;a=s.assets()[0]
    p={'source':first,'destination':second,'assets':[{'id':a['id'],'version':a['version']}],'date':'2026-10-29'}
    s.mutate(u,uid(),'move',p,lambda c:s.movement(c,u['id'],p))
    current=next(r for r in s.assets() if r['id']==a['id']);assert current['floor']=='1'
    p.update(source=second,destination=first,assets=[{'id':a['id'],'version':current['version']}],floor='')
    s.mutate(u,uid(),'move',p,lambda c:s.movement(c,u['id'],p))
    assert next(r for r in s.assets() if r['id']==a['id'])['floor']==''


def test_invalid_floor_does_not_conduct_movement(prepared):
    s,u,first,second=prepared;a=s.assets()[0];documents=len(s.read('SELECT * FROM documents'))
    for invalid in (None,2,['2']):
        p={'source':first,'destination':second,'assets':[{'id':a['id'],'version':a['version']}],'date':'2026-10-29','floor':invalid}
        with pytest.raises(ValueError):s.mutate(u,uid(),'move',p,lambda c:s.movement(c,u['id'],p))
    assert len(s.read('SELECT * FROM documents'))==documents
    assert next(r for r in s.assets() if r['id']==a['id'])['floor']=='1'


def test_gui_floor_allocation_move_returned_and_main_column(tmp_path):
    project=Path(__file__).resolve().parents[1]
    script=r'''
import sys
from pathlib import Path
from PySide6 import QtCore,QtWidgets as W
from fastapi.testclient import TestClient
from aho.core import uid
from aho.server import create_app
from aho.client import Client,COLUMNS
from aho.stock_dialog import StockMoveDialog
from aho.movement_dialog import MoveAssetsDialog
app=W.QApplication([]);root=Path(sys.argv[1]);server=create_app(root/'data');s=server.state.store
s.setup('admin','floor-test-password');token=s.login('Администратор','floor-test-password')['token'];u=s.user(token)
s.mutate(u,uid(),'import',{},lambda c:s.import_rows(c,[{'code':'0001','name':'Стул','unit':'шт','quantity':2,'rows':[2]}],'hash','test.xlsx'))
def loc(name,parent=None):return s.mutate(u,uid(),'location',{},lambda c:s.add_location(c,{'name':name,'parent':parent}))['id']
warehouse=loc('Здание');room=loc('Кабинет 201',warehouse);other=loc('Архив',warehouse)
http=TestClient(server)
class Window(Client):
    def api(self,path,payload=None):
        h={'Authorization':'Bearer '+self.token}
        r=http.get(path,headers=h) if payload is None else http.post(path,headers=h,json=payload)
        if r.is_error:raise RuntimeError(str(r.json().get('detail')))
        return r.json()
w=Window(local_url='http://127.0.0.1:8765',settings_root=root);w.token=token;w.refresh();w.show();app.processEvents()
d=StockMoveDialog(w,s.stock()[0]);d.warehouse.setCurrentIndex(d.warehouse.findData(warehouse));d.room.setCurrentIndex(d.room.findData(room));d.floor.setText('2');d.suffix_table.item(0,0).setText('/0001')
assert not d.sources.isAncestorOf(d.floor)
assert d.payload()[1]['floor']=='2'
d.grab().save(str(root/'floor_dialog.png'));d.submit();assert d.result is not None,d.error.text()
a=s.assets()[0];aid=a['id'];number=a['number'];assert a['floor']=='2'
def visible_floor(expected):
    w.refresh();w.view_tabs.setCurrentIndex(1);app.processEvents()
    column=next(i for i,(key,_) in enumerate(COLUMNS) if key=='floor')
    row=next(i for i in range(w.table.rowCount()) if w.table.item(i,0).data(QtCore.Qt.ItemDataRole.UserRole)==aid)
    assert w.table.item(row,column).text()==expected
visible_floor('2')
move=MoveAssetsDialog(w,[a]);move.destination=other;move.floor.setText('цоколь');move.submit()
assert move.result()==W.QDialog.DialogCode.Accepted,move.error.text()
visible_floor('цоколь')
a=s.assets()[0];back=MoveAssetsDialog(w,[a],True);back.submit();assert back.result()==W.QDialog.DialogCode.Accepted
assert s.assets()[0]['floor']==''
returned=StockMoveDialog(w,s.stock()[0]);returned.sources.setCurrentIndex(1)
returned.warehouse.setCurrentIndex(returned.warehouse.findData(warehouse));returned.room.setCurrentIndex(returned.room.findData(room))
returned.returned_table.item(0,0).setCheckState(QtCore.Qt.CheckState.Checked);returned.floor.setText('технический')
assert returned.payload()[1]['floor']=='технический'
returned.submit();assert returned.result is not None,returned.error.text()
visible_floor('технический')
a=s.assets()[0];assert a['id']==aid and a['number']==number and len(s.assets())==1
w.grab().save(str(root/'floor_column.png'));w.close();print('FLOOR_UI_OK')
'''
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],cwd=project,env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=25)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'FLOOR_UI_OK' in result.stdout
