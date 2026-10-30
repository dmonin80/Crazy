"""Read-only client routing and local-disk server checks."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def is_network_path(path):
    text=str(path)
    if text.startswith(('\\\\','//')):return True
    if os.name=='nt':
        import ctypes
        anchor=Path(path).resolve().anchor
        return bool(anchor and ctypes.windll.kernel32.GetDriveTypeW(anchor)==4)
    return False


def require_local_server_root(root):
    if is_network_path(root):
        raise ValueError('Сервер нужно запускать на компьютере с базой по локальному пути, например D:\\AHO_Inventory. Запуск сервера с сетевого диска запрещён. На остальных ПК запускайте клиент.')


def read_network_settings(root):
    path=Path(root)/'network.json'
    if not path.exists():return None
    result=json.loads(path.read_text('utf-8-sig'))
    address=result.get('server_url','').rstrip('/')
    parsed=urlsplit(address)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('В network.json укажите server_url вида http://pc00527:8765')
    result['server_url']=address
    if result.get('ca_file'):
        ca=Path(result['ca_file']);result['ca_file']=str(ca if ca.is_absolute() else Path(root)/ca)
    return result
