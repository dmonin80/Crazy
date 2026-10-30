import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from aho.local_runtime import (VERSION, control, ensure_local_server, is_our_server,
                               read_config, stop_local_server, url)
from aho.server import create_app


def test_local_controls_disabled_on_regular_server(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/local/status').status_code == 404
        assert client.post('/local/setup',json={'name':'bad','password':'bad'}).status_code == 404


def test_local_controls_require_secret(tmp_path):
    config={'instance_id':'test','control_token':'secret'}
    with TestClient(create_app(tmp_path,local_config=config),client=('127.0.0.1',50000)) as client:
        assert client.get('/local/status').status_code == 403
        assert client.post('/local/setup',headers={'X-Local-Token':'wrong'},json={'name':'Администратор','password':'long-enough-password'}).status_code == 403
        headers={'X-Local-Token':'secret'}
        assert client.get('/local/status',headers=headers).json()['setup_required']
        assert client.post('/local/setup',headers=headers,json={'name':'Администратор','password':'long-enough-password'}).status_code == 200
        assert not client.get('/local/status',headers=headers).json()['setup_required']
        assert client.post('/local/setup',headers=headers,json={'name':'other','password':'long-enough-password'}).status_code == 409


def test_start_reuse_restart_same_data(tmp_path):
    root=tmp_path/'Программа АХО с пробелами'
    try:
        first=ensure_local_server(root)
        assert url(first).startswith('http://127.0.0.1:')
        assert control(first,'/local/status')['setup_required']
        control(first,'/local/setup',{'name':'Администратор','password':'local-test-password'})
        again=ensure_local_server(root)
        assert again==first
        assert not control(again,'/local/status')['setup_required']
        # A different server configuration must never match this listener.
        impostor=dict(first,root_key='other-copy')
        with httpx.Client(timeout=1,trust_env=False) as client:
            assert not is_our_server(impostor,client)
            info=client.get(url(first)+'/health').json()
            assert info['version']==VERSION
        assert stop_local_server(root)
        assert not stop_local_server(root)
        after=ensure_local_server(root)
        assert after['instance_id']==first['instance_id']
        assert not control(after,'/local/status')['setup_required']
        with httpx.Client(timeout=2,trust_env=False) as client:
            response=client.post(url(after)+'/login',json={'name':'Администратор','password':'local-test-password'})
            assert response.status_code==200
    finally:
        stop_local_server(root)


def test_concurrent_launches_and_foreign_port(tmp_path):
    root=tmp_path/'copy'
    root.mkdir()
    # Hold a real foreign listener; the local server must choose another port.
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(5)
    from aho.local_runtime import write_config
    import uuid,secrets
    preferred=listener.getsockname()[1]
    write_config(root,{'instance_id':str(uuid.uuid4()),'control_token':secrets.token_urlsafe(32),'port':preferred})
    try:
        with ThreadPoolExecutor(2) as pool:
            configs=list(pool.map(lambda _:ensure_local_server(root),range(2)))
        assert configs[0]==configs[1]
        assert configs[0]['port']!=preferred
        assert listener.getsockname()[1]==preferred
    finally:
        stop_local_server(root)
        listener.close()


def test_corrupt_config_not_overwritten(tmp_path):
    root=tmp_path/'broken';root.mkdir();config=root/'local_server.json';config.write_text('{bad')
    with pytest.raises(ValueError):ensure_local_server(root)
    assert config.read_text()=='{bad'


def test_combined_gui_first_setup_and_server_survives_close(tmp_path):
    root=tmp_path/'gui'
    project=Path(__file__).resolve().parents[1]
    script=r'''
import sys
from pathlib import Path
from PySide6 import QtCore,QtWidgets as W
from aho.client import Client
from run_inventory import desktop
root=Path(sys.argv[1])
state={'setup':False,'logged_in':False}
def drive():
    for widget in W.QApplication.topLevelWidgets():
        if isinstance(widget,W.QDialog) and widget.windowTitle()=='Первый запуск — администратор':
            edits=widget.findChildren(W.QLineEdit)
            edits[0].setText('Администратор');edits[1].setText('gui-test-password');edits[2].setText('gui-test-password')
            box=widget.findChild(W.QDialogButtonBox)
            box.button(W.QDialogButtonBox.StandardButton.Ok).click()
            state['setup']=True
        if isinstance(widget,Client) and widget.token:
            assert widget.local_url.startswith('http://127.0.0.1:')
            assert widget.rows==[]
            state['logged_in']=True;widget.close()
    if not state['logged_in']:QtCore.QTimer.singleShot(100,drive)
OriginalApp=W.QApplication
class AutoApp(OriginalApp):
    def __init__(self,*args):
        super().__init__(*args)
        QtCore.QTimer.singleShot(100,drive)
W.QApplication=AutoApp
code=desktop(root)
assert code==0 and all(state.values()),state
print('GUI_SETUP_AND_LOGIN_OK')
'''
    try:
        result=subprocess.run([sys.executable,'-c',script,str(root)],cwd=project,
                              env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=25)
        assert result.returncode==0,result.stdout+'\n'+result.stderr
        assert 'GUI_SETUP_AND_LOGIN_OK' in result.stdout
        config=read_config(root)
        # Closing the Qt client must not terminate the detached server.
        assert not control(config,'/local/status')['setup_required']
    finally:
        stop_local_server(root)

def test_copied_settings_do_not_connect_to_other_folder(tmp_path):
    import shutil
    source=tmp_path/'source';copy=tmp_path/'copy'
    try:
        one=ensure_local_server(source)
        control(one,'/local/setup',{'name':'Администратор','password':'source-test-password'})
        copy.mkdir()
        shutil.copy2(source/'local_server.json',copy/'local_server.json')
        two=ensure_local_server(copy)
        assert one['instance_id']==two['instance_id']
        assert one['root_key']!=two['root_key']
        assert one['port']!=two['port']
        assert control(two,'/local/status')['setup_required']
        assert not control(one,'/local/status')['setup_required']
    finally:
        stop_local_server(copy)
        stop_local_server(source)
