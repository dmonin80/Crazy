"""Human-readable asset card and movement timeline."""

import json
from PySide6 import QtCore, QtWidgets as W


class AssetDialog(W.QDialog):
    def __init__(self, parent, asset, history):
        super().__init__(parent)
        self.setWindowTitle("Карточка имущества · " + asset["number"])
        self.resize(900, 650)
        layout = W.QVBoxLayout(self)
        title = W.QLabel(asset["name"])
        title.setWordWrap(True)
        title.setStyleSheet("font-size:20px;font-weight:600;color:#16324F")
        layout.addWidget(title)
        tabs = W.QTabWidget()
        layout.addWidget(tabs)
        details = W.QWidget()
        form = W.QFormLayout(details)
        for key, label in [
            ("number", "Инвентарный номер"),
            ("code", "Код 1С"),
            ("quantity", "Количество"),
            ("unit", "Единица измерения"),
            ("location_name", "Место хранения"),
            ("floor", "Этаж"),
            ("responsible", "Ответственный"),
            ("supplier", "Поставщик"),
            ("note", "Примечание"),
        ]:
            value = W.QLabel(str(asset.get(key, "")))
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
            )
            form.addRow(label, value)
        tabs.addTab(details, "Сведения")
        table = W.QTableWidget(len(history), 5)
        table.setHorizontalHeaderLabels(
            ["Дата", "Документ", "Откуда", "Куда", "Комментарий"]
        )
        table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        for i, row in enumerate(history):
            before = json.loads(row["before_json"]) if row.get("before_json") else {}
            after = json.loads(row["after_json"])
            for j, value in enumerate(
                [
                    row["date"],
                    row["number"] or row["kind"],
                    before.get("location_name", "Первичное распределение"),
                    after.get("location_name", ""),
                    row.get("comment", ""),
                ]
            ):
                table.setItem(i, j, W.QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(table, "История перемещений")
        qr = W.QLabel("Для печати QR-кода выберите «Этикетка PDF».")
        if asset.get("database_uuid"):
            import qrcode
            from io import BytesIO
            from PySide6 import QtGui

            output = BytesIO()
            qrcode.make(f"INV1:{asset['database_uuid']}:{asset['id']}").save(
                output, format="PNG"
            )
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(output.getvalue())
            qr.setPixmap(
                pixmap.scaled(
                    160,
                    160,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(qr)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Close)
        buttons.button(W.QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        pdf = buttons.addButton(
            "Этикетка PDF", W.QDialogButtonBox.ButtonRole.ActionRole
        )
        pdf.setEnabled(
            parent.current_user.get("is_admin")
            or "labels" in parent.current_user.get("permissions", [])
        )

        def label():
            path, _ = W.QFileDialog.getSaveFileName(
                self,
                "Сохранить этикетку",
                asset["number"].replace("/", "_") + ".pdf",
                "PDF (*.pdf)",
            )
            if path:
                from pathlib import Path

                Path(path).write_bytes(parent.api("/labels", {"assets": [asset["id"]]}))

        pdf.clicked.connect(lambda: parent.safe(label))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
