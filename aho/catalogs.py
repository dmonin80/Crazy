"""Versioned business directories, migration and server-side reference validation."""
import json
from .core import Conflict, uid

TABLES = {'responsibles': 'responsibles', 'suppliers': 'suppliers'}


def migrate(store, existed):
    version = store.read("SELECT value FROM meta WHERE key='schema_version'")[0]['value']
    if version in ('2','3'):
        return
    if version != '1':
        raise ValueError('Неподдерживаемая версия базы: ' + version)
    if existed:
        store.backup()
    with store.transaction() as c:
        if c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '2':
            return
        for table in TABLES.values():
            c.execute(f'''CREATE TABLE {table}(id TEXT PRIMARY KEY,name TEXT NOT NULL,details TEXT NOT NULL DEFAULT '',
                         archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),version INTEGER NOT NULL DEFAULT 1)''')
        c.execute('ALTER TABLE locations ADD COLUMN version INTEGER NOT NULL DEFAULT 1')
        c.execute('ALTER TABLE assets ADD COLUMN responsible_id TEXT REFERENCES responsibles(id)')
        c.execute('ALTER TABLE assets ADD COLUMN supplier_id TEXT REFERENCES suppliers(id)')
        c.execute("ALTER TABLE assets ADD COLUMN supplier TEXT NOT NULL DEFAULT ''")
        # Preserve existing names verbatim. Do not merge different strings or invent departments.
        for row in c.execute("SELECT DISTINCT responsible FROM assets WHERE trim(responsible)!=''").fetchall():
            ident = uid()
            c.execute('INSERT INTO responsibles(id,name) VALUES(?,?)', (ident, row[0]))
            c.execute('UPDATE assets SET responsible_id=? WHERE responsible=?', (ident, row[0]))
        c.execute("UPDATE meta SET value='2' WHERE key='schema_version'")


def list_entries(store, kind):
    if kind == 'locations':
        return store.locations()
    if kind not in TABLES:
        raise ValueError('Неизвестный справочник')
    return store.read(f'SELECT * FROM {TABLES[kind]} ORDER BY name,details,id')


def check_duplicate(c, table, name, parent=None, exclude=None, confirmed=False):
    rows = c.execute(f'SELECT * FROM {table}').fetchall()
    for row in rows:
        if row['id'] == exclude:
            continue
        same = row['name'].strip().casefold() == name.strip().casefold()
        if table == 'locations':
            same = same and row['parent'] == parent
        if same and not confirmed:
            raise Conflict('В справочнике уже есть запись с таким именем. Проверьте совпадения и подтвердите создание отдельной записи.')


def create_entry(c, kind, p):
    if kind not in TABLES:
        raise ValueError('Неизвестный справочник')
    name, details = validate_fields(p)
    table = TABLES[kind]
    check_duplicate(c, table, name, confirmed=p.get('confirm_duplicate') is True)
    ident = uid()
    c.execute(f'INSERT INTO {table}(id,name,details) VALUES(?,?,?)', (ident, name, details))
    return {'id': ident, 'version': 1}


def validate_fields(p):
    if not isinstance(p.get('name'), str) or not p['name'].strip():
        raise ValueError('Название / ФИО обязательно')
    details = p.get('details', '')
    if not isinstance(details, str):
        raise ValueError('Дополнительные реквизиты должны быть текстом')
    return p['name'].strip(), details.strip()


def update_entry(c, kind, ident, p):
    table = 'locations' if kind == 'locations' else TABLES.get(kind)
    if table is None:
        raise ValueError('Неизвестный справочник')
    row = c.execute(f'SELECT * FROM {table} WHERE id=?', (ident,)).fetchone()
    if not row:
        raise ValueError('Запись не найдена')
    if ident == 'zero' and table == 'locations':
        raise ValueError('Нулевой склад является системным и не изменяется')
    if type(p.get('version')) is not int or p['version'] != row['version']:
        raise Conflict('Запись уже изменена другим пользователем. Обновите справочник.')
    action = p.get('action', 'edit')
    before = dict(row)
    if action == 'edit':
        if row['archived']:
            raise Conflict('Сначала восстановите запись из архива')
        name, details = validate_fields(p)
        if table == 'locations':
            if p.get('parent', row['parent']) != row['parent']:
                raise ValueError('Родительский склад после создания записи не меняется')
            check_duplicate(c, table, name, row['parent'], ident, p.get('confirm_duplicate') is True)
            c.execute('UPDATE locations SET name=?,version=version+1 WHERE id=?', (name, ident))
        else:
            check_duplicate(c, table, name, exclude=ident, confirmed=p.get('confirm_duplicate') is True)
            c.execute(f'UPDATE {table} SET name=?,details=?,version=version+1 WHERE id=?', (name, details, ident))
    elif action in ('archive', 'restore'):
        if table == 'locations':
            if action == 'archive':
                if c.execute('SELECT 1 FROM assets WHERE location=? LIMIT 1', (ident,)).fetchone():
                    raise Conflict('Нельзя архивировать склад с имуществом. Сначала переместите имущество.')
                if c.execute('SELECT 1 FROM locations WHERE parent=? AND archived=0 LIMIT 1', (ident,)).fetchone():
                    raise Conflict('Сначала архивируйте активные подсклады')
            elif row['parent']:
                parent = c.execute('SELECT archived FROM locations WHERE id=?', (row['parent'],)).fetchone()
                if not parent or parent['archived']:
                    raise Conflict('Сначала восстановите родительский склад')
        c.execute(f'UPDATE {table} SET archived=?,version=version+1 WHERE id=?', (int(action == 'archive'), ident))
    else:
        raise ValueError('Неизвестная операция справочника')
    after = dict(c.execute(f'SELECT * FROM {table} WHERE id=?', (ident,)).fetchone())
    return {'id': ident, 'version': after['version'], 'before': before, 'after': after}


def assignments(c, p, existing=None):
    result = {}
    for field, table in (('responsible', 'responsibles'), ('supplier', 'suppliers')):
        key = field + '_id'
        if key not in p and field not in p and existing is not None:
            result[key] = existing[key]
            result[field] = existing[field]
            continue
        ident = p.get(key)
        if key not in p and p.get(field):
            # Compatibility with older requests is limited to an unambiguous existing entry.
            matches = c.execute(f'SELECT * FROM {table} WHERE name=? AND archived=0', (p[field],)).fetchall()
            if len(matches) != 1:
                raise ValueError('Выберите ' + ('ответственное лицо' if field == 'responsible' else 'поставщика') + ' из справочника. Создайте запись заранее; при совпадении ФИО используйте ID.')
            ident = matches[0]['id']
        if ident is None:
            result[key], result[field] = None, ''
            continue
        if not isinstance(ident, str):
            raise ValueError('Некорректная ссылка на справочник')
        row = c.execute(f'SELECT * FROM {table} WHERE id=? AND archived=0', (ident,)).fetchone()
        if not row:
            raise ValueError('Выбранная запись отсутствует или архивирована. Обновите список.')
        result[key], result[field] = ident, row['name']
    return result


def asset_snapshot(c, asset):
    result = dict(asset)
    if 'quantity_decimal' in result:
        from .quantities import number
        result['quantity']=number(result['quantity_decimal'])
    location = c.execute('SELECT l.name,l.parent,p.name AS parent_name FROM locations l LEFT JOIN locations p ON p.id=l.parent WHERE l.id=?', (asset['location'],)).fetchone()
    result['location_name'] = ((location['parent_name'] + ' / ') if location['parent'] else '') + location['name']
    for field, table in (('responsible', 'responsibles'), ('supplier', 'suppliers')):
        if asset[field + '_id']:
            row = c.execute(f'SELECT name,details FROM {table} WHERE id=?', (asset[field + '_id'],)).fetchone()
            if row:
                result[field] = row['name']
                result[field + '_details'] = row['details']
    return result
