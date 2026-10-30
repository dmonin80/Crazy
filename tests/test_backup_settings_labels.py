import uuid
import pytest
from fastapi.testclient import TestClient
from aho.server import create_app
from aho.core import Conflict


def test_backup_management_and_restore(tmp_path):
    app = create_app(tmp_path)
    store = app.state.store
    store.setup("admin", "backup-test-password")
    with TestClient(app) as client:
        token = store.login("Администратор", "backup-test-password")["token"]
        h = {"Authorization": "Bearer " + token}
        user = store.user(token)
        filename = client.post("/backup", headers=h, json={}).json()["filename"]
        with store.transaction() as c:
            c.execute("INSERT INTO locations(id,name) VALUES('later','Поздняя запись')")
        rows = client.get("/backups", headers=h).json()
        assert rows[0]["filename"] == filename and rows[0]["created_at"]
        assert (
            client.post(
                "/backups/delete",
                headers=h,
                json={"filename": "../inventory.sqlite3", "confirm": True},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/backups/restore", headers=h, json={"filename": filename}
            ).status_code
            == 400
        )
        result = client.post(
            "/backups/restore", headers=h, json={"filename": filename, "confirm": True}
        )
        assert result.status_code == 200, result.text
        assert not store.read("SELECT id FROM locations WHERE id='later'")
        assert store.backup_path(result.json()["safety_backup"]).exists()
        assert client.get("/me", headers=h).status_code == 403
        with pytest.raises(PermissionError):
            store.mutate(user, str(uuid.uuid4()), "location", {}, lambda c: None)
        token = store.login("Администратор", "backup-test-password")["token"]
        h = {"Authorization": "Bearer " + token}
        assert (
            client.post(
                "/backups/delete",
                headers=h,
                json={"filename": filename, "confirm": True},
            ).status_code
            == 200
        )
        assert not (tmp_path / "backups" / filename).exists()


def test_foreign_backup_rejected(tmp_path):
    from aho.core import Store
    import shutil

    s = Store(tmp_path / "one")
    s.setup("admin", "backup-test-password")
    other = Store(tmp_path / "two")
    copy = other.backup()
    shutil.copy2(copy, s.root / "backups" / copy.name)
    u = s.user(s.login("Администратор", "backup-test-password")["token"])
    with pytest.raises(ValueError, match="другой базе"):
        s.restore_backup(copy.name, u)


def test_label_contains_number_and_name():
    from aho.labels import make_pdf
    import pymupdf

    asset = {"id": str(uuid.uuid4()), "number": "001/1", "name": "Стул офисный"}
    for template in ("40x30", "58x40", "A4"):
        pdf = make_pdf([asset], str(uuid.uuid4()), template)
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            text = "".join(page.get_text() for page in doc)
            assert "Стул офисный" in text and "001/1" in text


def test_refresh_setting_controls_timer(tmp_path):
    from PySide6 import QtCore, QtWidgets as W
    from aho.client import Client
    from run_inventory import enable_periodic_refresh

    app = W.QApplication.instance() or W.QApplication([])
    w = Client(server_url="http://127.0.0.1:1")
    w.preferences = QtCore.QSettings(
        str(tmp_path / "prefs.ini"), QtCore.QSettings.Format.IniFormat
    )
    w.preferences.setValue("refresh_seconds", 0)
    timer = enable_periodic_refresh(w)
    assert not timer.isActive()
    w.preferences.setValue("refresh_seconds", 45)
    timer = enable_periodic_refresh(w)
    assert timer.isActive() and timer.interval() == 45000
    w.close()
