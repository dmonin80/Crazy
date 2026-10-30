import base64
import hashlib
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager, closing, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from .quantities import (
    quantity,
    number as qnumber,
    text as qtext,
    total as qtotal,
    subtract as qsubtract,
    mode as qmode,
)


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


class Conflict(ValueError):
    pass


def synchronized(method):
    from functools import wraps

    @wraps(method)
    def call(self, *args, **kwargs):
        with self._maintenance_lock:
            return method(self, *args, **kwargs)

    return call


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in ("imports", "backups", "labels"):
            (self.root / folder).mkdir(exist_ok=True)
        self.path = self.root / "inventory.sqlite3"
        import threading

        self._maintenance_lock = threading.RLock()
        self._generation = 0
        self._login_lock = threading.Lock()
        self._login_attempts = {}
        existed = self.path.exists()
        with closing(self.connect()) as c:
            c.executescript("""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT UNIQUE NOT NULL,salt TEXT NOT NULL,hash TEXT NOT NULL,role TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS locations(id TEXT PRIMARY KEY,name TEXT NOT NULL,parent TEXT REFERENCES locations(id),archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY,hash TEXT UNIQUE NOT NULL,name TEXT NOT NULL,at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,code TEXT UNIQUE NOT NULL,name TEXT NOT NULL,unit TEXT NOT NULL,initial INTEGER NOT NULL CHECK(initial>=0),import_id TEXT NOT NULL REFERENCES imports(id),source_rows TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,item_id TEXT NOT NULL REFERENCES items(id),suffix TEXT NOT NULL,number TEXT UNIQUE NOT NULL,location TEXT NOT NULL REFERENCES locations(id),responsible TEXT NOT NULL DEFAULT '',floor TEXT NOT NULL DEFAULT '',note TEXT NOT NULL DEFAULT '',version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,kind TEXT NOT NULL,date TEXT NOT NULL,number TEXT NOT NULL,comment TEXT NOT NULL,at TEXT NOT NULL,user_id TEXT NOT NULL REFERENCES users(id));
CREATE TABLE IF NOT EXISTS lines(document_id TEXT NOT NULL REFERENCES documents(id),asset_id TEXT NOT NULL REFERENCES assets(id),before_json TEXT,after_json TEXT NOT NULL,PRIMARY KEY(document_id,asset_id));
CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,signature TEXT NOT NULL,result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,at TEXT NOT NULL,user_id TEXT NOT NULL,action TEXT NOT NULL,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,name TEXT NOT NULL,state TEXT NOT NULL,at TEXT NOT NULL,location TEXT REFERENCES locations(id));
CREATE TABLE IF NOT EXISTS checks(session_id TEXT NOT NULL REFERENCES sessions(id),asset_id TEXT NOT NULL REFERENCES assets(id),snapshot TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'Не проверено',actual TEXT,comment TEXT NOT NULL DEFAULT '',version INTEGER NOT NULL DEFAULT 1,checked_at TEXT,checked_by TEXT REFERENCES users(id),PRIMARY KEY(session_id,asset_id));
CREATE TABLE IF NOT EXISTS findings(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),description TEXT NOT NULL,at TEXT NOT NULL,user_id TEXT NOT NULL REFERENCES users(id));
""")
            c.execute("INSERT OR IGNORE INTO meta VALUES('database_uuid',?)", (uid(),))
            c.execute("INSERT OR IGNORE INTO meta VALUES('schema_version','1')")
            c.execute(
                "INSERT OR IGNORE INTO locations(id,name) VALUES('zero','Нулевой склад')"
            )
            c.commit()
        original_schema = self.read(
            "SELECT value FROM meta WHERE key='schema_version'"
        )[0]["value"]
        from .catalogs import migrate

        migrate(self, existed)
        from .quantities import migrate as migrate_quantities

        migrate_quantities(self, existed and original_schema == "2")

        from .security import migrate

        migrate(self)

    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @contextmanager
    def transaction(self):
        with self._maintenance_lock:
            c = self.connect()
            try:
                c.execute("BEGIN IMMEDIATE")
                yield c
                c.commit()
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()

    @synchronized
    def read(self, sql, args=()):
        with closing(self.connect()) as c:
            return [dict(r) for r in c.execute(sql, args)]

    def audit(self, c, user, action, data):
        c.execute(
            "INSERT INTO audit VALUES(?,?,?,?,?)",
            (uid(), now(), user, action, json.dumps(data, ensure_ascii=False)),
        )

    def setup(self, name, password):
        name = "Администратор"
        if len(password) < 12:
            raise ValueError("Пароль должен содержать минимум 12 символов")
        with self.transaction() as c:
            if c.execute("SELECT 1 FROM users").fetchone():
                raise Conflict("Администратор уже создан")
            salt = secrets.token_hex(16)
            digest = hashlib.scrypt(
                password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
            ).hex()
            user = uid()
            c.execute(
                "INSERT INTO users(id,name,salt,hash,role) VALUES(?,?,?,?,?)",
                (user, name, salt, digest, "admin"),
            )
            self.audit(c, user, "setup", {"name": name})

    def login(self, name, password):
        import time
        from fastapi import HTTPException

        # Throttle per account; bound memory even for invented account names.
        key = name.strip().casefold()
        with self._login_lock:
            stamp = time.monotonic()
            self._login_attempts = {
                k: [t for t in v if stamp - t < 60]
                for k, v in self._login_attempts.items()
                if v and stamp - v[-1] < 60
            }
            attempts = self._login_attempts.setdefault(key, [])
            if (
                len(attempts) >= 10
                or sum(map(len, self._login_attempts.values())) >= 200
            ):
                raise HTTPException(
                    429,
                    "Слишком много попыток входа. Повторите через минуту.",
                    headers={"Retry-After": "60"},
                )
            attempts.append(stamp)
        rows = self.read("SELECT * FROM users WHERE name=? AND active=1", (name,))
        row = rows[0] if rows else None
        # Expensive password hashing must not hold SQLite's writer lock.
        salt = row["salt"] if row else "00" * 16
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
        ).hex()
        if not row or not secrets.compare_digest(row["hash"], digest):
            raise ValueError("Неверное имя или пароль")
        with self.transaction() as c:
            current = c.execute(
                "SELECT hash,active FROM users WHERE id=?", (row["id"],)
            ).fetchone()
            if not current or not current["active"] or current["hash"] != row["hash"]:
                raise ValueError("Учётная запись изменена. Повторите вход")
            c.execute("DELETE FROM tokens WHERE expires<=?", (time.time(),))
            token = secrets.token_urlsafe(32)
            c.execute(
                "INSERT INTO tokens VALUES(?,?,?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    row["id"],
                    time.time() + 28800,
                ),
            )
        with self._login_lock:
            self._login_attempts.pop(key, None)
        return {"token": token, "role": row["role"], "name": name}

    @synchronized
    def user(self, token):
        import time

        rows = self.read(
            "SELECT u.id,u.name,u.role FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.hash=? AND t.expires>? AND u.active=1",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        )
        if not rows:
            raise PermissionError("Требуется вход")
        from .security import enrich

        result = enrich(self, rows[0])
        result["_generation"] = self._generation
        return result

    @synchronized
    def mutate(
        self,
        user,
        request_id,
        action,
        payload,
        handler,
        admin=False,
        before_mutation=None,
    ):
        from .security import require, action_permission, enrich

        if user.get("_generation", self._generation) != self._generation:
            raise PermissionError("База восстановлена. Войдите снова")
        user = enrich(self, dict(user))
        if action == "batch-transfer":
            for line in payload.get("lines", []):
                require(user, "allocate" if line.get("kind") == "allocate" else "move")
        else:
            require(
                user,
                "return"
                if action == "move" and payload.get("destination") == "zero"
                else action_permission(action),
            )
        uuid.UUID(request_id)
        signature = hashlib.sha256(
            json.dumps([action, payload], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        with self.transaction() as c:
            old = c.execute(
                "SELECT * FROM requests WHERE id=?", (request_id,)
            ).fetchone()
            if old:
                if old["user_id"] != user["id"] or old["signature"] != signature:
                    raise Conflict("ID запроса уже использован для другой операции")
                return json.loads(old["result"])
            if before_mutation:
                before_mutation()
            result = handler(c)
            audit_data = (
                dict(payload, before=result["before"], after=result["after"])
                if isinstance(result, dict) and "before" in result and "after" in result
                else payload
            )
            if action == "import":
                audit_data = {k: v for k, v in payload.items() if k != "data"}
                audit_data["file_sha256"] = hashlib.sha256(
                    base64.b64decode(payload.get("data", ""))
                ).hexdigest()
                audit_data["result"] = result
            self.audit(c, user["id"], action, audit_data)
            c.execute(
                "INSERT INTO requests VALUES(?,?,?,?)",
                (request_id, user["id"], signature, json.dumps(result)),
            )
            return result

    def locations(self):
        return self.read("SELECT * FROM locations ORDER BY name")

    def add_location(self, c, p):
        from .catalogs import validate_fields, check_duplicate

        name, _ = validate_fields(p)
        parent = p.get("parent") or None
        if parent:
            row = c.execute(
                "SELECT * FROM locations WHERE id=? AND archived=0", (parent,)
            ).fetchone()
            if not row or row["parent"] or parent == "zero":
                raise ValueError("Выберите основной склад")
        check_duplicate(
            c, "locations", name, parent, confirmed=p.get("confirm_duplicate") is True
        )
        ident = uid()
        c.execute(
            "INSERT INTO locations(id,name,parent) VALUES(?,?,?)", (ident, name, parent)
        )
        return {"id": ident}

    def import_rows(self, c, rows, digest, filename, update=False):
        if c.execute("SELECT 1 FROM imports WHERE hash=?", (digest,)).fetchone():
            raise Conflict("Этот файл уже импортирован")
        if c.execute("SELECT 1 FROM imports").fetchone() and not update:
            raise Conflict(
                "Для обновления существующей базы подтвердите обновление выгрузки"
            )
        ident = uid()
        c.execute(
            "INSERT INTO imports VALUES(?,?,?,?)", (ident, digest, filename, now())
        )
        for r in rows:
            q = quantity(r["quantity"])
            existing = c.execute(
                "SELECT * FROM items WHERE code=?", (r["code"],)
            ).fetchone()
            if existing:
                cards = c.execute(
                    "SELECT quantity_decimal FROM assets WHERE item_id=?",
                    (existing["id"],),
                ).fetchall()
                used = qtotal(a["quantity_decimal"] for a in cards)
                if q < used:
                    raise Conflict(
                        f"Код {r['code']}: количество {qtext(q)} меньше уже созданных карточек ({qtext(used)}). Обновление отменено"
                    )
                if cards and existing["unit"] != r["unit"]:
                    raise Conflict(
                        f"Код {r['code']}: нельзя изменить единицу измерения при наличии карточек. Обновление отменено"
                    )
                c.execute(
                    "UPDATE items SET name=?,unit=?,initial=?,import_id=?,source_rows=?,initial_decimal=?,tracking_mode=? WHERE id=?",
                    (
                        r["name"],
                        r["unit"],
                        int(q) if q == q.to_integral_value() and q <= 2**63 - 1 else 0,
                        ident,
                        json.dumps(r["rows"]),
                        qtext(q),
                        r.get("tracking_mode", qmode(r["unit"], q)),
                        existing["id"],
                    ),
                )
                continue
            c.execute(
                "INSERT INTO items(id,code,name,unit,initial,import_id,source_rows,initial_decimal,tracking_mode) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    uid(),
                    r["code"],
                    r["name"],
                    r["unit"],
                    int(q) if q == q.to_integral_value() and q <= 2**63 - 1 else 0,
                    ident,
                    json.dumps(r["rows"]),
                    qtext(q),
                    r.get("tracking_mode", qmode(r["unit"], q)),
                ),
            )
        return {
            "positions": len(rows),
            "units": qnumber(qtotal(r["quantity"] for r in rows)),
        }

    @synchronized
    def stock(self, connection=None):
        with (
            nullcontext(connection)
            if connection is not None
            else closing(self.connect())
        ) as c:
            if connection is None:
                c.execute("BEGIN")
            items = [dict(r) for r in c.execute("SELECT * FROM items ORDER BY name")]
            assets = c.execute(
                "SELECT item_id,location,quantity_decimal FROM assets"
            ).fetchall()
        by_item = {r["id"]: [] for r in items}
        for a in assets:
            by_item[a["item_id"]].append(a)
        for r in items:
            rows = by_item[r["id"]]
            r["initial"] = qnumber(r["initial_decimal"])
            r["unassigned"] = qnumber(
                qsubtract(
                    r["initial_decimal"], qtotal(a["quantity_decimal"] for a in rows)
                )
            )
            r["returned"] = qnumber(
                qtotal(a["quantity_decimal"] for a in rows if a["location"] == "zero")
            )
            r["allocated"] = qnumber(
                qtotal(a["quantity_decimal"] for a in rows if a["location"] != "zero")
            )
        return items

    @synchronized
    def assets(self, connection=None):
        sql = """SELECT a.*,i.name,i.code,i.unit,i.tracking_mode,
CASE WHEN l.parent IS NULL THEN l.name ELSE p.name || ' / ' || l.name END AS location_name,l.parent,
CASE WHEN l.parent IS NULL THEN l.name ELSE p.name END AS object,
CASE WHEN l.parent IS NULL THEN '' ELSE l.name END AS room,
COALESCE(r.name,a.responsible) AS responsible_name,COALESCE(r.details,'') AS responsible_details,
COALESCE(s.name,a.supplier) AS supplier_name,COALESCE(s.details,'') AS supplier_details
FROM assets a JOIN items i ON i.id=a.item_id JOIN locations l ON l.id=a.location
LEFT JOIN locations p ON p.id=l.parent LEFT JOIN responsibles r ON r.id=a.responsible_id
LEFT JOIN suppliers s ON s.id=a.supplier_id ORDER BY i.name,a.number"""
        rows = (
            self.read(sql)
            if connection is None
            else [dict(r) for r in connection.execute(sql)]
        )
        for row in rows:
            row["responsible"] = row.pop("responsible_name")
            row["supplier"] = row.pop("supplier_name")
            row["quantity"] = qnumber(row["quantity_decimal"])
            if quantity(row["quantity_decimal"]) != 1:
                row["tracking_mode"] = "quantity"
        return rows

    def movement(self, c, user, p, allocate=False, document_id=None):
        from datetime import date
        from .catalogs import assignments, asset_snapshot

        date.fromisoformat(p["date"])
        if "floor" in p and not isinstance(p["floor"], str):
            raise ValueError(
                "Этаж должен быть текстом: например, 2, цоколь или технический"
            )
        destination = c.execute(
            "SELECT * FROM locations WHERE id=? AND archived=0", (p["destination"],)
        ).fetchone()
        if not destination or (allocate and destination["id"] == "zero"):
            raise ValueError("Неверный склад назначения")
        doc = document_id or uid()
        if document_id is None:
            c.execute(
                "INSERT INTO documents VALUES(?,?,?,?,?,?,?)",
                (
                    doc,
                    "allocate" if allocate else "move",
                    p["date"],
                    p.get("number", ""),
                    p.get("comment", ""),
                    now(),
                    user,
                ),
            )
        ids = []
        if allocate:
            amount = quantity(p["quantity"], positive=True)
            item = c.execute(
                "SELECT * FROM items WHERE id=?", (p["item_id"],)
            ).fetchone()
            if not item:
                raise ValueError("Номенклатура не найдена")
            piece = (
                item["tracking_mode"] == "piece"
                and amount == amount.to_integral_value()
            )
            if piece and amount > 10000:
                raise ValueError(
                    "Для индивидуальных карточек укажите целое количество от 1 до 10000"
                )
            count = int(amount) if piece else 1
            consumed = qtotal(
                r[0]
                for r in c.execute(
                    "SELECT quantity_decimal FROM assets WHERE item_id=?", (item["id"],)
                )
            )
            if qsubtract(item["initial_decimal"], consumed) < amount:
                raise Conflict("Недостаточно нераспределённого остатка")
            suffixes = p.get("suffixes")
            if (
                not isinstance(suffixes, list)
                or len(suffixes) != count
                or any(
                    not isinstance(value, str) or not value.strip()
                    for value in suffixes
                )
            ):
                raise ValueError(
                    "Введите вручную дополнение к исходному коду для каждой перемещаемой единицы"
                )
            if any(
                value != value.strip()
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
                for value in suffixes
            ):
                raise ValueError(
                    "Дополнения не должны содержать управляющие символы или пробелы в начале / конце"
                )
            numbers = [item["code"] + suffix for suffix in suffixes]
            if len(set(numbers)) != len(numbers):
                raise Conflict(
                    "Дополнения в одной операции должны давать разные инвентарные номера"
                )
            for offset in range(0, len(numbers), 500):
                batch = numbers[offset : offset + 500]
                taken = c.execute(
                    "SELECT number FROM assets WHERE number IN ("
                    + ",".join("?" for _ in batch)
                    + ") LIMIT 1",
                    batch,
                ).fetchone()
                if taken:
                    raise Conflict(
                        "Инвентарный номер уже существует: "
                        + taken["number"]
                        + ". Введите другое дополнение."
                    )
            refs = assignments(c, p)
            for suffix, number in zip(suffixes, numbers):
                ident = uid()
                c.execute(
                    "INSERT INTO assets(id,item_id,suffix,number,location,responsible,floor,note,responsible_id,supplier_id,supplier,quantity_decimal) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        ident,
                        item["id"],
                        suffix,
                        number,
                        p["destination"],
                        refs["responsible"],
                        p.get("floor", ""),
                        p.get("note", ""),
                        refs["responsible_id"],
                        refs["supplier_id"],
                        refs["supplier"],
                        "1" if piece else qtext(amount),
                    ),
                )
                after = asset_snapshot(
                    c, c.execute("SELECT * FROM assets WHERE id=?", (ident,)).fetchone()
                )
                c.execute(
                    "INSERT INTO lines VALUES(?,?,?,?)",
                    (doc, ident, None, json.dumps(after)),
                )
                ids.append(ident)
        else:
            selected = p["assets"]
            if not selected or len({a["id"] for a in selected}) != len(selected):
                raise ValueError("Выберите разные карточки")
            for a in selected:
                row = c.execute(
                    "SELECT * FROM assets WHERE id=?", (a["id"],)
                ).fetchone()
                if (
                    not row
                    or row["version"] != a["version"]
                    or row["location"] != p["source"]
                ):
                    raise Conflict("Карточка уже изменена. Обновите данные")
                before = asset_snapshot(c, row)
                refs = assignments(c, p, row)
                amount = quantity(
                    a.get("quantity", row["quantity_decimal"]), positive=True
                )
                current = quantity(row["quantity_decimal"])
                if amount > current:
                    raise Conflict(
                        "Запрошенное количество больше количества в карточке"
                    )
                if amount < current:
                    item = c.execute(
                        "SELECT code,tracking_mode FROM items WHERE id=?",
                        (row["item_id"],),
                    ).fetchone()
                    suffix = a.get("suffix")
                    if (
                        not isinstance(suffix, str)
                        or not suffix.strip()
                        or suffix != suffix.strip()
                        or any(ord(ch) < 32 or ord(ch) == 127 for ch in suffix)
                    ):
                        raise ValueError(
                            "Для отделяемой части введите дополнение к коду новой карточки"
                        )
                    new_number = item["code"] + suffix
                    if c.execute(
                        "SELECT 1 FROM assets WHERE number=?", (new_number,)
                    ).fetchone():
                        raise Conflict(
                            "Инвентарный номер уже существует: " + new_number
                        )
                    new_id = uid()
                    c.execute(
                        "UPDATE assets SET quantity_decimal=?,version=version+1 WHERE id=?",
                        (qtext(qsubtract(current, amount)), a["id"]),
                    )
                    remainder = asset_snapshot(
                        c,
                        c.execute(
                            "SELECT * FROM assets WHERE id=?", (a["id"],)
                        ).fetchone(),
                    )
                    c.execute(
                        "INSERT INTO lines VALUES(?,?,?,?)",
                        (doc, a["id"], json.dumps(before), json.dumps(remainder)),
                    )
                    c.execute(
                        "INSERT INTO assets(id,item_id,suffix,number,location,responsible,floor,note,responsible_id,supplier_id,supplier,quantity_decimal) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            new_id,
                            row["item_id"],
                            suffix,
                            new_number,
                            p["destination"],
                            refs["responsible"],
                            p.get("floor", row["floor"]),
                            row["note"],
                            refs["responsible_id"],
                            refs["supplier_id"],
                            refs["supplier"],
                            qtext(amount),
                        ),
                    )
                    after = asset_snapshot(
                        c,
                        c.execute(
                            "SELECT * FROM assets WHERE id=?", (new_id,)
                        ).fetchone(),
                    )
                    c.execute(
                        "INSERT INTO lines VALUES(?,?,?,?)",
                        (doc, new_id, None, json.dumps(after)),
                    )
                    ids.extend([a["id"], new_id])
                    continue
                c.execute(
                    "UPDATE assets SET location=?,responsible=?,responsible_id=?,supplier_id=?,supplier=?,floor=?,version=version+1 WHERE id=?",
                    (
                        p["destination"],
                        refs["responsible"],
                        refs["responsible_id"],
                        refs["supplier_id"],
                        refs["supplier"],
                        p.get("floor", row["floor"]),
                        a["id"],
                    ),
                )
                after = asset_snapshot(
                    c,
                    c.execute("SELECT * FROM assets WHERE id=?", (a["id"],)).fetchone(),
                )
                c.execute(
                    "INSERT INTO lines VALUES(?,?,?,?)",
                    (doc, a["id"], json.dumps(before), json.dumps(after)),
                )
                ids.append(a["id"])
        return {"document_id": doc, "assets": ids}

    def batch_movement(self, c, user, p):
        from datetime import date

        date.fromisoformat(p["date"])
        lines = p.get("lines")
        if not isinstance(lines, list) or not lines or len(lines) > 500:
            raise ValueError("Выберите от 1 до 500 наименований")
        ids = [line.get("item_id") for line in lines]
        if any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("В списке должны быть разные наименования")
        doc = uid()
        c.execute(
            "INSERT INTO documents VALUES(?,?,?,?,?,?,?)",
            (
                doc,
                "batch",
                p["date"],
                p.get("number", ""),
                p.get("comment", ""),
                now(),
                user,
            ),
        )
        assets = []
        for line in lines:
            common = {
                k: p[k]
                for k in (
                    "destination",
                    "date",
                    "number",
                    "comment",
                    "floor",
                    "responsible_id",
                    "supplier_id",
                )
                if k in p
            }
            kind = line.get("kind")
            if kind == "allocate":
                common.update(
                    item_id=line["item_id"],
                    quantity=line.get("quantity"),
                    suffixes=line.get("suffixes"),
                    note=line.get("note", ""),
                )
            elif kind == "move":
                selected = line.get("assets", [])
                if not selected:
                    raise ValueError("Выберите возвращённые карточки")
                for a in selected:
                    row = c.execute(
                        "SELECT item_id,location FROM assets WHERE id=?", (a.get("id"),)
                    ).fetchone()
                    if (
                        not row
                        or row["item_id"] != line["item_id"]
                        or row["location"] != "zero"
                    ):
                        raise Conflict(
                            "Карточка уже изменена или не находится на Нулевом складе"
                        )
                common.update(source="zero", assets=selected)
            else:
                raise ValueError("Неизвестный вид строки перемещения")
            result = self.movement(c, user, common, kind == "allocate", doc)
            assets.extend(result["assets"])
        return {"document_id": doc, "assets": assets}

    def start_session(self, c, p):
        from .catalogs import asset_snapshot

        ident = uid()
        location = p.get("location") or None
        if (
            location
            and not c.execute(
                "SELECT 1 FROM locations WHERE id=?", (location,)
            ).fetchone()
        ):
            raise ValueError("Склад не найден")
        c.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?)",
            (ident, p["name"], "В работе", now(), location),
        )
        rows = c.execute(
            "SELECT a.*,i.code,i.name,l.name AS location_name FROM assets a JOIN items i ON i.id=a.item_id JOIN locations l ON l.id=a.location WHERE (? IS NULL OR a.location=? OR l.parent=?)",
            (location, location, location),
        ).fetchall()
        for row in rows:
            c.execute(
                "INSERT INTO checks(session_id,asset_id,snapshot) VALUES(?,?,?)",
                (
                    ident,
                    row["id"],
                    json.dumps(asset_snapshot(c, row), ensure_ascii=False),
                ),
            )
        return {"id": ident, "count": len(rows)}

    def resolve(self, text):
        if text.startswith("INV") and ":" in text:
            parts = text.split(":")
            if len(parts) != 3 or parts[0] != "INV1":
                raise ValueError("Формат QR не поддерживается")
            for part in parts[1:]:
                uuid.UUID(part)
            if (
                parts[1]
                != self.read("SELECT value FROM meta WHERE key='database_uuid'")[0][
                    "value"
                ]
            ):
                raise Conflict("Код другой базы")
            rows = self.read("SELECT * FROM assets WHERE id=?", (parts[2],))
        else:
            rows = self.read("SELECT * FROM assets WHERE number=?", (text,))
        if not rows:
            raise ValueError("Карточка не найдена")
        return rows[0]

    def scan(self, c, user, sid, p):
        asset = self.resolve(p["text"])
        row = c.execute(
            "SELECT * FROM checks WHERE session_id=? AND asset_id=?", (sid, asset["id"])
        ).fetchone()
        if not row:
            raise Conflict("Имущество вне состава сессии. Зарегистрируйте находку.")
        snapshot = json.loads(row["snapshot"])
        status = (
            "В наличии"
            if p["actual"] == snapshot["location"]
            else "Обнаружено в другом месте"
        )
        result = self.check(
            c,
            user,
            sid,
            {
                "asset_id": asset["id"],
                "version": row["version"],
                "status": status,
                "actual": p["actual"],
                "fast": p.get("fast", False),
            },
        )
        return dict(result, number=asset["number"], status=status)

    def check(self, c, user, sid, p):
        session = c.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if not session or session["state"] != "В работе":
            raise Conflict("Сессия не находится в работе")
        row = c.execute(
            "SELECT * FROM checks WHERE session_id=? AND asset_id=?",
            (sid, p["asset_id"]),
        ).fetchone()
        if not row:
            raise Conflict("Имущество вне состава. Зарегистрируйте находку отдельно")
        if row["version"] != p["version"]:
            raise Conflict("Результат уже изменён другим проверяющим")
        asset = c.execute(
            "SELECT * FROM assets WHERE id=?", (p["asset_id"],)
        ).fetchone()
        snapshot = json.loads(row["snapshot"])
        if p.get("fast") and p["status"] != "В наличии":
            raise Conflict("Быстрая проверка допускает только наличие")
        if p.get("fast") and (
            asset["version"] != snapshot["version"]
            or p["actual"] != snapshot["location"]
            or row["status"] != "Не проверено"
        ):
            raise Conflict(
                "Повторная проверка или расхождение. Требуется ручное подтверждение"
            )
        if p["status"] not in (
            "В наличии",
            "Не найдено",
            "Обнаружено в другом месте",
            "Не проверено",
        ):
            raise ValueError("Неверный статус")
        if (
            p.get("actual")
            and not c.execute(
                "SELECT 1 FROM locations WHERE id=?", (p["actual"],)
            ).fetchone()
        ):
            raise ValueError("Фактическое место не найдено")
        if p["status"] == "В наличии" and p.get("actual") != snapshot["location"]:
            raise ValueError(
                "Фактическое место отличается: выберите статус расхождения"
            )
        c.execute(
            "UPDATE checks SET status=?,actual=?,comment=?,version=version+1,checked_at=?,checked_by=? WHERE session_id=? AND asset_id=?",
            (
                p["status"],
                p.get("actual"),
                p.get("comment", ""),
                now(),
                user,
                sid,
                p["asset_id"],
            ),
        )
        return {
            "version": row["version"] + 1,
            "movement_warning": asset["version"] != snapshot["version"],
        }

    @synchronized
    def backup(self):
        target = (
            self.root
            / "backups"
            / (
                datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_")
                + uid()
                + ".sqlite3"
            )
        )
        with (
            closing(self.connect()) as source,
            closing(sqlite3.connect(target)) as dest,
        ):
            source.backup(dest)
            if (
                dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or dest.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise ValueError("Резервная копия не прошла проверку")
        return target

    def backup_path(self, filename):
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename.endswith(".sqlite3")
        ):
            raise ValueError("Некорректное имя резервной копии")
        path = self.root / "backups" / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError("Резервная копия не найдена")
        return path

    @synchronized
    def list_backups(self):
        result = []
        for path in (self.root / "backups").glob("*.sqlite3"):
            if path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            result.append(
                {
                    "filename": path.name,
                    "created_at": datetime.fromtimestamp(
                        stat.st_mtime, timezone.utc
                    ).isoformat(),
                    "size": stat.st_size,
                }
            )
        return sorted(result, key=lambda row: row["created_at"], reverse=True)

    @synchronized
    def delete_backup(self, filename, actor):
        path = self.backup_path(filename)
        with self.transaction() as c:
            self.audit(c, actor["id"], "backup.delete", {"filename": filename})
        path.unlink()
        return {"deleted": True}

    @synchronized
    def restore_backup(self, filename, actor):
        path = self.backup_path(filename)
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
            if (
                source.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
                or source.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise ValueError("Копия повреждена")
            metadata = dict(source.execute("SELECT key,value FROM meta"))
            current = dict(
                (r["key"], r["value"]) for r in self.read("SELECT key,value FROM meta")
            )
            if metadata.get("database_uuid") != current.get("database_uuid"):
                raise ValueError("Копия принадлежит другой базе")
            if metadata.get("schema_version") != current.get("schema_version"):
                raise ValueError("Версия схемы копии отличается")
            with closing(self.connect()) as live:
                tables = [
                    r[0]
                    for r in live.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                ]
                for table in tables:
                    live_columns = [
                        tuple(r)
                        for r in live.execute("PRAGMA table_info(" + table + ")")
                    ]
                    backup_columns = list(
                        source.execute("PRAGMA table_info(" + table + ")")
                    )
                    if live_columns != backup_columns:
                        raise ValueError("Структура копии отличается: " + table)
            safety = self.backup()
            with closing(self.connect()) as destination:
                source.backup(destination)
        self._generation += 1
        with self.transaction() as c:
            c.execute("DELETE FROM tokens")
            self.audit(
                c,
                actor["id"],
                "backup.restore",
                {"filename": filename, "safety_backup": safety.name},
            )
        return {"restored": True, "safety_backup": safety.name, "login_required": True}
