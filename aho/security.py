"""User permissions are checked by the server on every request."""
import json
import hashlib
import secrets
from .core import uid

PERMISSIONS = {
    'import': 'Импорт и обновление данных 1С',
    'catalogs': 'Изменение справочников',
    'allocate': 'Распределение с Нулевого склада',
    'move': 'Перемещение между складами',
    'return': 'Возврат на Нулевой склад',
    'inventory': 'Проведение инвентаризации',
    'labels': 'Печать этикеток PDF',
    'export': 'Экспорт XLSX',
    'audit': 'Просмотр журнала действий',
    'backup': 'Создание резервной копии',
}

def migrate(store):
    with store.transaction() as c:
        cols={r['name'] for r in c.execute('PRAGMA table_info(users)')}
        if 'permissions' not in cols:
            c.execute("ALTER TABLE users ADD COLUMN permissions TEXT NOT NULL DEFAULT '[]'")
            c.execute('UPDATE users SET permissions=? WHERE role!=?',(json.dumps(['allocate','move','return','inventory','labels','export']),'viewer'))
        if not c.execute("SELECT 1 FROM meta WHERE key='permanent_admin'").fetchone():
            row=c.execute("SELECT id FROM users WHERE role='admin' ORDER BY rowid LIMIT 1").fetchone()
            if row:
                c.execute("UPDATE users SET name='Администратор',active=1 WHERE id=?",(row['id'],))
                c.execute("INSERT INTO meta VALUES('permanent_admin',?)",(row['id'],))

def enrich(store,user):
    rows=store.read("SELECT value FROM meta WHERE key='permanent_admin'")
    if not rows:
        migrate(store)
        rows=store.read("SELECT value FROM meta WHERE key='permanent_admin'")
    user['is_admin']=bool(rows and rows[0]['value']==user['id'])
    user['permissions']=list(PERMISSIONS) if user['is_admin'] else json.loads(store.read('SELECT permissions FROM users WHERE id=?',(user['id'],))[0]['permissions'])
    return user

def require(user,permission):
    if not user.get('is_admin') and permission not in user.get('permissions',[]):
        raise PermissionError('Нет разрешения: '+PERMISSIONS.get(permission,permission))

def admin_only(user):
    if not user.get('is_admin'):raise PermissionError('Управление пользователями доступно только Администратору')

def action_permission(action):
    if action.startswith('catalog.') or action=='location':return 'catalogs'
    if action.startswith(('session.','finding:')):return 'inventory'
    return {'import':'import','allocate':'allocate','batch-transfer':'move','move':'move','return':'return'}.get(action,action)

def save_user(store,actor,p):
    admin_only(actor)
    name=str(p.get('name','')).strip()
    if not name:raise ValueError('Укажите имя пользователя')
    permissions=p.get('permissions',[])
    if not isinstance(permissions,list) or any(x not in PERMISSIONS for x in permissions):raise ValueError('Неизвестное разрешение')
    password=p.get('password','')
    if password and len(password)<12:raise ValueError('Пароль должен содержать минимум 12 символов')
    with store.transaction() as c:
        ident=p.get('id')
        old=c.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone() if ident else None
        if ident and not old:raise ValueError('Пользователь не найден')
        permanent=c.execute("SELECT value FROM meta WHERE key='permanent_admin'").fetchone()['value']
        if ident==permanent:
            if name!='Администратор' or not p.get('active',True):raise ValueError('Администратор постоянный: переименование и отключение запрещены')
            permissions=list(PERMISSIONS)
        if not old and not password:raise ValueError('Задайте пароль новому пользователю')
        if c.execute('SELECT 1 FROM users WHERE name=? AND id!=?',(name,ident or '')).fetchone():raise ValueError('Имя уже используется')
        ident=ident or uid()
        salt=secrets.token_hex(16) if password else old['salt']
        digest=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex() if password else old['hash']
        role='admin' if ident==permanent else 'custom'
        c.execute('INSERT INTO users(id,name,salt,hash,role,active,permissions) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,salt=excluded.salt,hash=excluded.hash,role=excluded.role,active=excluded.active,permissions=excluded.permissions',(ident,name,salt,digest,role,int(bool(p.get('active',True))),json.dumps(permissions)))
        c.execute('DELETE FROM tokens WHERE user_id=?',(ident,))
        store.audit(c,actor['id'],'user.save',{'id':ident,'name':name,'active':bool(p.get('active',True)),'permissions':permissions})
    return {'id':ident}
