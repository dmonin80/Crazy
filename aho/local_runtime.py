"""Local server supervisor. One data directory, detached process, loopback only."""
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

VERSION = '0.3.1'
SERVICE = 'aho_inventory'


def app_root():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


class FileLock:
    """OS releases locks after a crash; stale files do not block startup."""
    def __init__(self, path):
        self.path = Path(path)
        self.file = None

    def acquire(self, timeout=20):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        if self.path.stat().st_size == 0:
            self.file.write(b'0')
            self.file.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.file.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.file.close()
                    self.file = None
                    raise TimeoutError('Сервер запускается другим экземпляром. Повторите запуск позже.')
                time.sleep(0.1)

    def close(self):
        if self.file is not None:
            try:
                self.file.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            finally:
                self.file.close()
                self.file = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.close()


def write_config(root, config):
    root = Path(root)
    temporary = root / ('local_server.' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        os.replace(temporary, root / 'local_server.json')
    finally:
        temporary.unlink(missing_ok=True)


def read_config(root):
    config = json.loads((Path(root) / 'local_server.json').read_text('utf-8'))
    uuid.UUID(config['instance_id'])
    if type(config['port']) is not int or not 1 <= config['port'] <= 65535 or len(config['control_token']) < 32:
        raise ValueError('Повреждены локальные настройки сервера')
    config['root_key'] = hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode()).hexdigest()
    return config


def url(config):
    return 'http://127.0.0.1:' + str(config['port'])


def is_our_server(config, client):
    try:
        response = client.get(url(config) + '/health')
        info = response.json() if response.status_code == 200 else {}
        return (info.get('service') == SERVICE and info.get('instance_id') == config['instance_id'] and info.get('root_key') == config['root_key'])
    except (httpx.HTTPError, ValueError):
        return False


def control(config, endpoint, payload=None, timeout=5):
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        if not is_our_server(config, client):
            raise RuntimeError('Локальный сервер этой папки недоступен')
        response = client.request('GET' if payload is None else 'POST', url(config) + endpoint,
                                  json=payload, headers={'X-Local-Token': config['control_token']})
        if response.is_error:
            raise RuntimeError(str(response.json().get('detail', 'Ошибка локального сервера')))
        return response.json()


def ensure_local_server(root, timeout=25, progress=None, lan=False):
    from .network import require_local_server_root
    require_local_server_root(root)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    # Serializes double-clicks and different desktop processes using this folder.
    startup_lock = FileLock(root / 'local_start.lock')
    startup_lock.acquire(timeout)
    try:
        try:
            config = read_config(root)
        except FileNotFoundError:
            config = {'instance_id': str(uuid.uuid4()), 'control_token': secrets.token_urlsafe(32), 'port': 8765}
            write_config(root, config)
            config = read_config(root)
        with httpx.Client(timeout=0.4, trust_env=False) as client:
            if is_our_server(config, client):
                info = client.get(url(config) + '/health').json()
                if info.get('version') != VERSION:
                    raise RuntimeError('Работает другая версия локального сервера. Остановите его перед обновлением.')
                if config.get('listen_host','127.0.0.1') != ('0.0.0.0' if lan else '127.0.0.1'):
                    raise RuntimeError('Работает сервер в другом режиме. Остановите его через меню «Система» перед сменой режима.')
                return config
            config['listen_host']='0.0.0.0' if lan else '127.0.0.1'
            if lan:config['port']=8765
            write_config(root,config)
            logs = root / 'data' / 'logs'
            logs.mkdir(parents=True, exist_ok=True)
            log_path = logs / 'local_server.log'
            if getattr(sys, 'frozen', False):
                command = [sys.executable, '--server-child', '--root', str(root)]
            else:
                command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'run_inventory.py'),
                           '--server-child', '--root', str(root)]
            kwargs = {'cwd': str(root), 'stdin': subprocess.DEVNULL}
            if os.name == 'nt':
                kwargs['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs['start_new_session'] = True
            with log_path.open('ab') as log:
                process = subprocess.Popen(command, stdout=log, stderr=log, **kwargs)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                config = read_config(root)  # Child may choose a free port if 8765 is occupied.
                if is_our_server(config, client):
                    return config
                if process.poll() is not None:
                    raise RuntimeError('Не удалось запустить локальный сервер. См. ' + str(log_path))
                if progress:
                    progress()
                time.sleep(0.1)
            # Never kill an unknown process or erase a database on a timeout.
            raise TimeoutError('Сервер не ответил вовремя. См. ' + str(log_path))
    finally:
        startup_lock.close()


def run_server_child(root):
    from .network import require_local_server_root
    require_local_server_root(root)
    root = Path(root).resolve()
    lifetime_lock = FileLock(root / 'local_server.lock')
    try:
        lifetime_lock.acquire(timeout=0)
    except TimeoutError:
        return
    try:
        config = read_config(root)
        from .server import create_app
        import uvicorn
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if os.name == 'nt':
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                listener.bind((config.get('listen_host','127.0.0.1'), config['port']))
            except OSError:
                if config.get('listen_host')=='0.0.0.0':
                    raise RuntimeError('Порт 8765 занят. Остановите другой сервер АХО или освободите порт.')
                # A different app owns the preferred port. Do not connect to or terminate it.
                listener.bind(('127.0.0.1', 0))
            listener.listen(128)
            config['port'] = listener.getsockname()[1]
            write_config(root, config)
            app = create_app(root / 'data', local_config=config)
            server = uvicorn.Server(uvicorn.Config(app, host=config.get('listen_host','127.0.0.1'), port=config['port'],
                                                  access_log=False, log_level='info'))
            app.state.local_shutdown = lambda: setattr(server, 'should_exit', True)
            server.run(sockets=[listener])
    finally:
        lifetime_lock.close()


def stop_local_server(root, timeout=15):
    from .network import require_local_server_root
    require_local_server_root(root)
    root = Path(root).resolve()
    lock = FileLock(root / 'local_start.lock')
    lock.acquire(timeout)
    try:
        try:
            config = read_config(root)
        except FileNotFoundError:
            return False
        with httpx.Client(timeout=0.5, trust_env=False) as client:
            if not is_our_server(config, client):
                # Distinguish an absent process from an unresponsive server.
                runtime = FileLock(root / 'local_server.lock')
                runtime.acquire(0)
                runtime.close()
                return False
        control(config, '/local/shutdown', {})
        runtime = FileLock(root / 'local_server.lock')
        runtime.acquire(timeout)  # Wait until graceful shutdown released SQLite and the lock.
        runtime.close()
        return True
    finally:
        lock.close()
