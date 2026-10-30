import os
from pathlib import Path
import subprocess
import sys


def test_directory_gui_and_movement_choices(tmp_path):
    project=Path(__file__).resolve().parents[1]
    script=r'''
import sys
from pathlib import Path
from PySide6 import QtWidgets as W
from fastapi.testclient import TestClient
from aho.client import Client
from aho.core import uid
from aho.server import create_app
from aho.directory_dialog import DirectoriesDialog,DirectoryEditor
from aho.stock_dialog import StockMoveDialog
from aho.movement_dialog import MoveAssetsDialog
app=W.QApplication([]);root=Path(sys.argv[1]);server=create_app(root/'data');s=server.state.store
s.setup('admin','gui-catalog-password');token=s.login('Администратор','gui-catalog-password')['token'];u=s.user(token)
s.mutate(u,uid(),'import',{},lambda c:s.import_rows(c,[{'code':'0001','name':'Стул','unit':'шт','quantity':3,'rows':[2]}],'test-hash','test.xlsx'))
http=TestClient(server)
class Window(Client):
    def api(self,path,payload=None):
        h={'Authorization':'Bearer '+self.token}
        r=http.get(path,headers=h) if payload is None else http.post(path,headers=h,json=payload)
        if r.is_error:raise RuntimeError(str(r.json().get('detail')))
        return r.json()
w=Window(local_url='http://127.0.0.1:8765',settings_root=root);w.token=token;w.refresh();w.show()
assert any(b.text()=='Справочники' for b in w.findChildren(W.QPushButton))
d=DirectoriesDialog(w);d.show();app.processEvents();assert d.tabs.count()==5
assert d.tabs.tabText(0)=='Склады' and d.tabs.tabText(2)=='Ответственные лица'
d.tables['warehouses'].selectRow(0);assert not d.edit_button.isEnabled() and not d.archive_button.isEnabled()
original_exec=DirectoryEditor.exec
values=[]
def fill_editor(e):
    kind,name,details,parent=values.pop(0)
    assert e.kind==kind
    e.name.setText(name);e.details.setText(details)
    if parent:e.parent.setCurrentIndex(e.parent.findData(parent))
    e.save();assert e.saved,e.error.text()
    return W.QDialog.DialogCode.Accepted
DirectoryEditor.exec=fill_editor
values.append(('warehouses','Главный склад','',None));d.add_button.click();assert not values
warehouse=next(r['id'] for r in d.data['locations'] if r['name']=='Главный склад')
d.tabs.setCurrentIndex(1);values.append(('rooms','Кабинет 101','',warehouse));d.add_button.click()
room=next(r['id'] for r in d.data['locations'] if r['name']=='Кабинет 101')
d.tabs.setCurrentIndex(2);values.append(('responsibles','Тестовый сотрудник','Отдел А',None));d.add_button.click()
person=d.data['responsibles'][0]['id'];d.tables['responsibles'].selectRow(0)
values.append(('responsibles','Тестовый сотрудник после правки','Отдел А',None));d.edit_button.click()
assert d.data['responsibles'][0]['id']==person and d.data['responsibles'][0]['version']==2
W.QMessageBox.question=lambda *a,**k:W.QMessageBox.StandardButton.Yes
d.tables['responsibles'].selectRow(0);d.archive_button.click();assert d.tables['responsibles'].rowCount()==0
d.archived.setChecked(True);d.tables['responsibles'].selectRow(0)
assert d.restore_button.isEnabled() and not d.edit_button.isEnabled()
d.restore_button.click();assert not d.data['responsibles'][0]['archived']
d.tabs.setCurrentIndex(3);values.append(('suppliers','Тестовый поставщик','ИНН 1234567890',None));d.add_button.click()
supplier=d.data['suppliers'][0]['id']
d.tabs.setCurrentIndex(4);assert not d.add_button.isEnabled() and d.tables['units'].item(0,0).text()=='шт'
d.tabs.setCurrentIndex(2);d.grab().save(str(root/'directories.png'))
d.close();w.refresh()
move=StockMoveDialog(w,s.stock()[0]);move.warehouse.setCurrentIndex(move.warehouse.findData(warehouse));move.room.setCurrentIndex(move.room.findData(room))
move.responsible.setCurrentIndex(move.responsible.findData(person));move.supplier.setCurrentIndex(move.supplier.findData(supplier));move.suffix_table.item(0,0).setText('/0001')
assert move.payload()[1]['responsible_id']==person and move.payload()[1]['supplier_id']==supplier
move.responsible.lineEdit().setText('Несуществующее ФИО')
try:move.payload();raise AssertionError('Unlisted text was accepted')
except ValueError:pass
move.responsible.setCurrentIndex(0);move.responsible.setCurrentIndex(move.responsible.findData(person))
move.grab().save(str(root/'catalog_choices.png'));move.submit();assert move.result is not None,move.error.text()
a=s.assets()[0];assert a['responsible_id']==person and a['supplier_id']==supplier and a['location']==room
w.refresh();w.view_tabs.setCurrentIndex(1)
assert 'Поставщик' in [w.table.horizontalHeaderItem(i).text() for i in range(w.table.columnCount())]
back=MoveAssetsDialog(w,[a],True);back.submit();assert back.result()==W.QDialog.DialogCode.Accepted,back.error.text()
a=s.assets()[0];assert a['location']=='zero' and a['responsible_id']==person and a['supplier_id']==supplier
with s.transaction() as c:c.execute("UPDATE users SET role='operator'")
readonly=DirectoriesDialog(w);assert not readonly.add_button.isEnabled()
readonly.close();w.close();DirectoryEditor.exec=original_exec
print('DIRECTORIES_GUI_OK')
'''
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],cwd=project,
                          env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'DIRECTORIES_GUI_OK' in result.stdout
