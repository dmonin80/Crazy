import json
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from aho.network import is_network_path,require_local_server_root,read_network_settings
from aho.server import create_app


def test_route_settings_and_network_root(tmp_path):
    assert is_network_path(r'\\pc00527\Distr\AHO_Inventory')
    with pytest.raises(ValueError):require_local_server_root(r'\\pc00527\Distr\AHO_Inventory')
    assert read_network_settings(tmp_path) is None
    path=tmp_path/'network.json';path.write_text(json.dumps({'server_url':'http://pc00527:8765'}))
    assert read_network_settings(tmp_path)['server_url']=='http://pc00527:8765'
    path.write_text(json.dumps({'server_url':'file:///data'}))
    with pytest.raises(ValueError):read_network_settings(tmp_path)


def test_remote_cannot_control_local_server(tmp_path):
    config={'instance_id':str(uuid.uuid4()),'control_token':'s'*40}
    app=create_app(tmp_path,local_config=config)
    remote=TestClient(app,client=('10.20.21.10',50000));local=TestClient(app,client=('127.0.0.1',50001))
    headers={'X-Local-Token':config['control_token']}
    for path in ('/local/status','/local/setup','/local/shutdown'):
        response=remote.get(path,headers=headers) if path.endswith('status') else remote.post(path,headers=headers,json={'name':'Администратор','password':'long-password-123'})
        assert response.status_code==403
    assert local.get('/local/status',headers=headers).status_code==200


def test_two_clients_one_database_and_competing_allocation(tmp_path):
    app=create_app(tmp_path);s=app.state.store;s.setup('Администратор','long-password-123')
    c1=TestClient(app,client=('10.20.21.1',50000));c2=TestClient(app,client=('10.20.21.2',50001))
    def headers(c):return {'Authorization':'Bearer '+c.post('/login',json={'name':'Администратор','password':'long-password-123'}).json()['token']}
    h1,h2=headers(c1),headers(c2)
    u=s.user(s.login('Администратор','long-password-123')['token'])
    s.mutate(u,str(uuid.uuid4()),'import',{},lambda db:s.import_rows(db,[{'name':'Стул','code':'01','unit':'шт','quantity':1,'rows':[2]}],'digest','one.xlsx'))
    loc=c1.post('/locations',headers=h1,json={'request_id':str(uuid.uuid4()),'name':'Офис'}).json()['id']
    item=c2.get('/stock',headers=h2).json()[0]['id']
    def allocate(pair):
        c,h=pair
        return c.post('/allocate',headers=h,json={'request_id':str(uuid.uuid4()),'item_id':item,'quantity':1,'suffixes':['/1'],'destination':loc,'date':'2026-10-29'}).status_code
    with ThreadPoolExecutor(2) as pool:codes=list(pool.map(allocate,[(c1,h1),(c2,h2)]))
    assert codes.count(200)==1 and any(code in (400,409) for code in codes)
    assert c1.get('/assets',headers=h1).json()==c2.get('/assets',headers=h2).json()
    assert len(c2.get('/assets',headers=h2).json())==1


def test_client_does_not_write_settings_or_open_database(tmp_path):
    from PySide6 import QtWidgets as W
    from aho.client import Client
    app=W.QApplication.instance() or W.QApplication([])
    root=tmp_path/'readonly-distribution' # Must not even be created.
    window=Client(settings_root=root,server_url='http://pc00527:8765')
    assert window.settings['server']=='http://pc00527:8765'
    assert not root.exists()
    assert 'Вход' in window.buttons
    window.close()
