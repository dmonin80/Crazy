"""Capture the actual desktop UI with disposable sample data, never a live database."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtWidgets as W
from fastapi.testclient import TestClient
from aho.server import create_app
from aho.core import uid
from aho.client import Client, APIError
from aho.catalogs import create_entry
from aho.asset_dialog import AssetDialog
from aho.inventory_dialog import InventoryDialog
from aho.documents_dialog import DocumentsDialog


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    output.mkdir(parents=True, exist_ok=True)
    qt = W.QApplication([])
    with TemporaryDirectory(prefix="aho-screens-") as temporary:
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
        QtCore.QSettings.setPath(
            QtCore.QSettings.Format.IniFormat,
            QtCore.QSettings.Scope.UserScope,
            temporary,
        )
        app = create_app(Path(temporary) / "data")
        s = app.state.store
        s.setup("admin", "screenshots-only-password")
        token = s.login("Администратор", "screenshots-only-password")["token"]
        u = s.user(token)
        rows = [
            {
                "name": n,
                "code": str(1000 + i),
                "unit": unit,
                "quantity": q,
                "rows": [i + 2],
            }
            for i, (n, unit, q) in enumerate(
                [
                    ("Стул офисный", "шт", 40),
                    ("Стол письменный", "шт", 20),
                    ("Монитор 24 дюйма", "шт", 15),
                    ("Шкаф для документов", "шт", 8),
                    ("Картридж для принтера", "шт", 25),
                    ("Кабель сетевой", "м", "125.5"),
                ]
            )
        ]
        s.mutate(
            u,
            uid(),
            "import",
            {},
            lambda c: s.import_rows(c, rows, "screens-demo", "demo.csv"),
        )
        office = s.mutate(
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
            lambda c: s.add_location(c, {"name": "Кабинет 201", "parent": office}),
        )["id"]
        person = s.mutate(
            u,
            uid(),
            "catalog.create:responsibles",
            {},
            lambda c: create_entry(
                c, "responsibles", {"name": "Иванова Анна Сергеевна"}
            ),
        )["id"]
        for item in s.stock():
            p = {
                "item_id": item["id"],
                "quantity": 2,
                "suffixes": ["/001", "/002"],
                "destination": room,
                "date": "2026-10-30",
                "number": "ПМ-001",
                "floor": "2",
                "responsible_id": person,
            }
            if item["unit"] == "м":
                p.update(quantity="12.5", suffixes=["/001"])
            s.mutate(u, uid(), "allocate", p, lambda c: s.movement(c, u["id"], p, True))
        with TestClient(app) as http:

            class Window(Client):
                def api(self, path, payload=None):
                    response = (
                        http.get(path, headers={"Authorization": "Bearer " + token})
                        if payload is None
                        else http.post(
                            path,
                            headers={"Authorization": "Bearer " + token},
                            json=payload,
                        )
                    )
                    if response.is_error:
                        raise APIError(response.text, response.status_code)
                    return response.json()

            w = Window(server_url="https://inventory.example.org")
            w.token = token
            w.refresh()
            w.show()
            qt.processEvents()
            w.grab().save(str(output / "main_window.png"))
            w.view_tabs.setCurrentIndex(1)
            w.table.setColumnWidth(0, 220)
            qt.processEvents()
            w.grab().save(str(output / "assets_window.png"))
            asset = s.assets()[0]
            asset = w.api("/assets/" + asset["id"])
            card = AssetDialog(w, asset, w.api("/history/" + asset["id"]))
            card.show()
            qt.processEvents()
            card.grab().save(str(output / "asset_card.png"))
            card.close()
            sid = w.command(
                "/sessions",
                {"name": "Проверка административного здания", "location": office},
            )["id"]
            inv = InventoryDialog(w, sid, "Проверка административного здания")
            inv.actual.setCurrentIndex(inv.actual.findData(room))
            inv.quick.setChecked(True)
            inv.scan.setText(asset["number"])
            inv.scan_asset()
            inv.show()
            qt.processEvents()
            inv.grab().save(str(output / "inventory_workspace.png"))
            inv.close()
            docs = DocumentsDialog(w)
            docs.show()
            qt.processEvents()
            docs.grab().save(str(output / "documents.png"))
            docs.close()
            w.close()
    print("Screenshots saved:", output)


if __name__ == "__main__":
    main()
