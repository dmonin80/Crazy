import json
import uuid
from aho.server import create_app
from aho.history import issued_lines
from fastapi.testclient import TestClient


def test_historical_documents_and_audit(tmp_path):
    app = create_app(tmp_path)
    s = app.state.store
    s.setup("admin", "readable-history-password")
    token = s.login("Администратор", "readable-history-password")["token"]
    u = s.user(token)

    def cmd(action, payload, handler):
        return s.mutate(u, str(uuid.uuid4()), action, payload, handler)

    cmd(
        "import",
        {},
        lambda c: s.import_rows(
            c,
            [
                {
                    "code": "01",
                    "name": "Кабель сетевой",
                    "unit": "м",
                    "quantity": "10",
                    "rows": [2],
                }
            ],
            "hash",
            "a.csv",
        ),
    )
    loc = cmd(
        "location", {"name": "Офис"}, lambda c: s.add_location(c, {"name": "Офис"})
    )["id"]
    other = cmd(
        "location", {"name": "Склад"}, lambda c: s.add_location(c, {"name": "Склад"})
    )["id"]
    p = {
        "item_id": s.stock()[0]["id"],
        "quantity": "10",
        "suffixes": ["/1"],
        "destination": loc,
        "date": "2026-10-30",
    }
    allocated = cmd("allocate", p, lambda c: s.movement(c, u["id"], p, True))
    asset = s.assets()[0]
    p = {
        "source": loc,
        "destination": other,
        "date": "2026-10-30",
        "assets": [
            {"id": asset["id"], "version": 1, "quantity": "2.5", "suffix": "/2"}
        ],
    }
    moved = cmd("move", p, lambda c: s.movement(c, u["id"], p))
    # Emulate legacy documents that do not carry nomenclature text in snapshots.
    with s.transaction() as c:
        for row in c.execute("SELECT rowid,* FROM lines").fetchall():
            for field in ("before_json", "after_json"):
                if row[field]:
                    snap = json.loads(row[field])
                    snap.pop("name", None)
                    snap.pop("unit", None)
                    c.execute(
                        "UPDATE lines SET " + field + "=? WHERE rowid=?",
                        (json.dumps(snap), row["rowid"]),
                    )
    with TestClient(app) as client:
        h = {"Authorization": "Bearer " + token}
        lines = client.get("/documents/" + moved["document_id"], headers=h).json()
        issued = issued_lines(lines)
        assert len(issued) == 1
        assert issued[0]["name"] == "Кабель сетевой" and issued[0]["unit"] == "м"
        assert (
            issued[0]["quantity"] == "2.5"
            and issued[0]["source"] == "Офис"
            and issued[0]["destination"] == "Склад"
        )
        audit = client.get("/audit", headers=h).json()
        move = next(row for row in audit if row["action"] == "move")
        assert move["actor_name"] == "Администратор"
        assert move["action_label"] == "Перемещение имущества"
        assert "Кабель сетевой" in move["summary"] and "2.5 м" in move["summary"]
        assert "Офис → Склад" in move["summary"]
        # Snapshot actor names survive renaming.
        with s.transaction() as c:
            c.execute("UPDATE users SET name='Переименованный' WHERE id=?", (u["id"],))
        assert (
            next(
                row
                for row in client.get("/audit", headers=h).json()
                if row["action"] == "move"
            )["actor_name"]
            == "Администратор"
        )


def test_document_html_and_print_button(tmp_path, monkeypatch):
    from PySide6 import QtWidgets as W, QtCore
    from aho.documents_dialog import DocumentsDialog

    app = W.QApplication.instance() or W.QApplication([])
    before = {
        "location": "a",
        "location_name": "Офис",
        "item_id": "i",
        "quantity_decimal": "2",
    }
    after = dict(
        before,
        location="b",
        location_name="Склад",
        number="01/1",
        name="Стул офисный",
        unit="шт",
    )

    class Client(W.QWidget):
        current_user = {"is_admin": True}

        def api(self, path, payload=None):
            if path == "/documents":
                return [
                    {
                        "id": "d",
                        "date": "2026-10-30",
                        "number": "42",
                        "kind": "move",
                        "author": "Анна",
                        "comment": "",
                    }
                ]
            return [
                {"before_json": json.dumps(before), "after_json": json.dumps(after)}
            ]

        def safe(self, fn):
            fn()

    client = Client()
    dialog = DocumentsDialog(client)
    dialog.table.selectRow(0)
    html = dialog.content()
    assert "Количество выдано" in html and "Единица измерения" in html
    assert (
        "Стул офисный" in html
        and "шт" in html
        and "Количество после операции" not in html
    )
    printed = []
    monkeypatch.setattr(
        dialog, "print_content", lambda content: printed.append(content)
    )

    def drive():
        child = next(
            w
            for w in W.QApplication.topLevelWidgets()
            if isinstance(w, W.QDialog) and w.windowTitle() == "Состав документа"
        )
        button = next(
            b for b in child.findChildren(W.QPushButton) if b.text() == "Печать"
        )
        button.click()
        child.accept()

    QtCore.QTimer.singleShot(0, drive)
    dialog.details()
    assert printed == [html]
    dialog.close()
    client.close()
