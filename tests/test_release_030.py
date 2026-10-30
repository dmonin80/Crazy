"""Regression coverage for the review findings and new workflows."""

import base64
import json
import time
import uuid
import pytest
from fastapi.testclient import TestClient
from PySide6 import QtCore, QtWidgets as W
from aho.server import create_app
from aho.client import Client, APIError, PendingOperation

PASSWORD = "release-test-password"


def rid():
    return str(uuid.uuid4())


@pytest.fixture
def api(tmp_path):
    app = create_app(tmp_path / "data")
    s = app.state.store
    s.setup("admin", PASSWORD)
    with TestClient(app, raise_server_exceptions=False) as c:
        token = c.post(
            "/login", json={"name": "Администратор", "password": PASSWORD}
        ).json()["token"]
        yield app, c, {"Authorization": "Bearer " + token}


@pytest.fixture
def qt(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    previous = QtCore.QSettings.defaultFormat()
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    QtCore.QSettings.setPath(
        QtCore.QSettings.Format.IniFormat,
        QtCore.QSettings.Scope.UserScope,
        str(tmp_path / "settings"),
    )
    yield app
    QtCore.QSettings.setDefaultFormat(previous)


@pytest.mark.parametrize(
    "route,payload",
    [
        ("/login", {}),
        ("/allocate", {}),
        (
            "/batch-transfer",
            {
                "request_id": "bad",
                "date": "2026-10-30",
                "destination": "zero",
                "lines": [1],
            },
        ),
        ("/labels", {"assets": []}),
        ("/resolve", {}),
    ],
)
def test_bad_input_is_client_error(api, route, payload):
    app, c, h = api
    r = c.post(route, headers=h, json=payload)
    assert r.status_code == 422, r.text
    assert PASSWORD not in r.text


def test_login_throttle(api):
    app, c, h = api
    for _ in range(10):
        assert (
            c.post(
                "/login", json={"name": "Администратор", "password": "wrong"}
            ).status_code
            == 400
        )
    assert (
        c.post(
            "/login", json={"name": "Администратор", "password": "wrong"}
        ).status_code
        == 429
    )


def test_import_retry_has_one_backup_and_compact_audit(api):
    app, c, h = api
    raw = "Номенклатура;Код;Ед. изм.;Количество\nСтул;001;шт;3".encode()
    p = {
        "data": base64.b64encode(raw).decode(),
        "filename": "data.csv",
        "mapping": {"name": 0, "code": 1, "unit": 2, "quantity": 3},
        "request_id": rid(),
    }
    first = c.post("/imports/commit", headers=h, json=p)
    assert first.status_code == 200, first.text
    assert c.post("/imports/commit", headers=h, json=p).json() == first.json()
    s = app.state.store
    assert len(list((s.root / "backups").glob("*.sqlite3"))) == 1
    audit = json.loads(
        s.read("SELECT data FROM audit WHERE action='import'")[0]["data"]
    )
    assert "data" not in audit and len(audit["file_sha256"]) == 64
    assert c.get("/overview", headers=h).json()["stock"][0]["initial"] == 3


def seed(app):
    s = app.state.store
    u = s.user(s.login("Администратор", PASSWORD)["token"])
    s.mutate(
        u,
        rid(),
        "import",
        {},
        lambda c: s.import_rows(
            c,
            [{"name": "Стул", "code": "001", "unit": "шт", "quantity": 2, "rows": [2]}],
            "digest",
            "test.csv",
        ),
    )
    loc = s.mutate(
        u, rid(), "location", {}, lambda c: s.add_location(c, {"name": "Офис"})
    )["id"]
    p = {
        "item_id": s.stock()[0]["id"],
        "quantity": 1,
        "suffixes": ["/1"],
        "destination": loc,
        "date": "2026-10-30",
    }
    s.mutate(u, rid(), "allocate", p, lambda c: s.movement(c, u["id"], p, True))
    return s, u, loc


def test_scan_idempotency_and_finished_session(api):
    app, c, h = api
    s, u, loc = seed(app)
    sid = c.post(
        "/sessions", headers=h, json={"request_id": rid(), "name": "Проверка"}
    ).json()["id"]
    p = {"request_id": rid(), "text": "001/1", "actual": loc, "fast": True}
    result = c.post("/sessions/" + sid + "/scan", headers=h, json=p)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "В наличии"
    assert (
        c.post("/sessions/" + sid + "/scan", headers=h, json=p).json() == result.json()
    )
    assert (
        c.post(
            "/sessions/" + sid + "/scan", headers=h, json=dict(p, request_id=rid())
        ).status_code
        == 409
    )
    assert (
        c.post(
            "/sessions/" + sid + "/finish",
            headers=h,
            json={"request_id": rid(), "confirm": True},
        ).status_code
        == 200
    )
    assert (
        c.post(
            "/sessions/" + sid + "/scan",
            headers=h,
            json=dict(p, request_id=rid(), fast=False),
        ).status_code
        == 409
    )


def test_restore_verifier_uses_temporary_copy(api):
    from verify_backup import verify

    app, c, h = api
    s, u, loc = seed(app)
    backup = s.backup()
    original = backup.read_bytes()
    database, count = verify(backup)
    assert count == 1 and backup.read_bytes() == original
    assert (
        database
        == s.read("SELECT value FROM meta WHERE key='database_uuid'")[0]["value"]
    )


def test_refresh_and_export_order(qt):
    w = Client(server_url="http://127.0.0.1:1")
    w.current_user = {"id": "a", "name": "admin", "is_admin": True}
    w.apply_permissions()
    assert w.buttons["Обновить"].isEnabled()
    w.stock_rows = [
        dict(
            id=i,
            name=n,
            code=i,
            unit="шт",
            initial=1,
            unassigned=1,
            returned=0,
            allocated=0,
            available=1,
        )
        for i, n in [("1", "Б"), ("2", "А")]
    ]
    w.populate()
    w.table.sortItems(0, QtCore.Qt.SortOrder.AscendingOrder)
    assert [r["name"] for r in w.displayed_rows()] == ["А", "Б"]
    w.search.setText("Б")
    assert [r["id"] for r in w.displayed_rows()] == ["1"]
    w.clear_filters()
    assert w.table.rowCount() == 2
    w.close()


def test_worker_keeps_event_loop_responsive(qt):
    from aho.tasks import wait_for_io

    beats = []
    timer = QtCore.QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: beats.append(1))
    timer.start()
    assert wait_for_io(None, lambda: (time.sleep(0.15), 42)[1]) == 42
    timer.stop()
    assert len(beats) >= 3


def test_pending_command_recovers_after_window_recreation(qt):
    sent = []
    stored = {}
    fail = [True]

    class TestWindow(Client):
        def api(self, path, payload=None):
            if path.startswith("/requests/"):
                key = path.rsplit("/", 1)[1]
                if key in stored:
                    return stored[key]
                raise APIError("not found", 404)
            sent.append(payload["request_id"])
            if fail[0]:
                raise PendingOperation("reply lost")
            stored[payload["request_id"]] = {"ok": True}
            return stored[payload["request_id"]]

    w = TestWindow(server_url="http://pending.test")
    w.current_user = {"id": "operator"}
    with pytest.raises(PendingOperation):
        w.command("/sessions", {"name": "Новая"})
    first = sent[0]
    w.close()
    fail[0] = False
    w = TestWindow(server_url="http://pending.test")
    w.current_user = {"id": "operator"}
    assert w.command("/sessions", {"name": "Новая"}) == {"ok": True}
    assert sent == [first, first]
    w.close()


def test_inventory_card_and_document_views(qt, api, tmp_path, monkeypatch):
    app, c, h = api
    s, u, loc = seed(app)

    class Window(Client):
        def api(self, path, payload=None):
            response = (
                c.get(path, headers=h)
                if payload is None
                else c.post(path, headers=h, json=payload)
            )
            if response.status_code >= 400:
                raise APIError(response.text, response.status_code)
            return response.json()

    w = Window(server_url="http://test")
    w.current_user = u
    w.refresh()
    from aho.asset_dialog import AssetDialog

    asset = s.assets()[0]
    card = AssetDialog(w, asset, w.api("/history/" + asset["id"]))
    assert card.findChild(W.QTabWidget).count() == 2
    card.close()
    sid = w.command("/sessions", {"name": "Тест"})["id"]
    from aho.inventory_dialog import InventoryDialog

    inv = InventoryDialog(w, sid, "Тест")
    inv.actual.setCurrentIndex(inv.actual.findData(loc))
    inv.quick.setChecked(True)
    inv.scan.setText(asset["number"])
    inv.scan_asset()
    assert "✓" in inv.feedback.text() and inv.rows[0]["status"] == "В наличии"
    monkeypatch.setattr(
        W.QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(tmp_path / "check.xlsx"), ""),
    )
    inv.export()
    from openpyxl import load_workbook

    with open(tmp_path / "check.xlsx", "rb") as f:
        wb = load_workbook(f)
        assert wb.active["E2"].value == "Офис"
        wb.close()
    inv.close()
    from aho.documents_dialog import DocumentsDialog

    docs = DocumentsDialog(w)
    docs.table.selectRow(0)
    assert "001/1" in docs.content()
    monkeypatch.setattr(
        W.QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(tmp_path / "movement.pdf"), ""),
    )
    docs.pdf()
    import pymupdf

    with pymupdf.open(tmp_path / "movement.pdf") as pdf:
        assert "001/1" in "".join(page.get_text() for page in pdf)
    docs.close()
    w.close()


def test_import_limits(monkeypatch):
    import aho.importer as importer

    monkeypatch.setattr(importer, "MAX_FILE_BYTES", 5)
    with pytest.raises(ValueError, match="20 МБ"):
        importer.read_table(b"123456", "a.csv")
