"""Create separate demo files; never overwrite an existing demo database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aho.core import Store, uid
from aho.catalogs import create_entry
from aho.importer import preview
from aho.labels import make_pdf
from openpyxl import Workbook

root = Path(__file__).resolve().parent
if (root / "demo_data" / "inventory.sqlite3").exists():
    raise SystemExit("Демо уже существует")
wb = Workbook()
ws = wb.active
ws.title = "Выгрузка 1С"
ws.append(["Демонстрационный пример"])
ws.append(["Номенклатура", "Код", "Единица измерения", "Количество"])
ws.append(["Стул офисный", 123, "шт", 20])
ws["B3"].number_format = "000000"
ws.append(["Монитор 24 дюйма", "000456", "шт", 5])
ws.append(["Стол письменный", "000789", "шт", 8])
wb.save(root / "import_example.xlsx")
s = Store(root / "demo_data")
s.setup("demo", "demo-password-only-2026")
u = s.user(s.login("Администратор", "demo-password-only-2026")["token"])
raw = (root / "import_example.xlsx").read_bytes()
p = preview(
    raw, "import_example.xlsx", {"name": 0, "code": 1, "unit": 2, "quantity": 3}, 2
)
s.mutate(
    u,
    uid(),
    "import",
    {},
    lambda c: s.import_rows(c, p["rows"], p["hash"], "import_example.xlsx"),
)
(root / "demo_data" / "imports" / (p["hash"] + ".xlsx")).write_bytes(raw)
loc = s.mutate(
    u,
    uid(),
    "location",
    {},
    lambda c: s.add_location(c, {"name": "Административное здание"}),
)["id"]
room = s.mutate(
    u,
    uid(),
    "location",
    {},
    lambda c: s.add_location(c, {"name": "Кабинет 101", "parent": loc}),
)["id"]
person = s.mutate(
    u,
    uid(),
    "catalog.create:responsibles",
    {},
    lambda c: create_entry(
        c, "responsibles", {"name": "Демонстрационный ответственный"}
    ),
)["id"]
for row in s.stock():
    payload = {
        "item_id": row["id"],
        "quantity": 2,
        "suffixes": ["/0001", "/0002"],
        "destination": room,
        "responsible_id": person,
        "floor": "1",
        "date": "2026-10-29",
        "number": "ДЕМО-001",
    }
    s.mutate(
        u, uid(), "allocate", payload, lambda c: s.movement(c, u["id"], payload, True)
    )
db = s.read("SELECT value FROM meta WHERE key='database_uuid'")[0]["value"]
(root / "labels_example.pdf").write_bytes(make_pdf(s.assets(), db, "58x40"))
(root / "labels_a4_example.pdf").write_bytes(make_pdf(s.assets(), db, "A4", skip=2))
s.mutate(
    u,
    uid(),
    "session",
    {},
    lambda c: s.start_session(
        c, {"name": "Демонстрационная проверка", "location": room}
    ),
)
with s.transaction() as c:
    c.execute("DELETE FROM tokens")
with s.connect() as c:
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
print("Demo generated")
