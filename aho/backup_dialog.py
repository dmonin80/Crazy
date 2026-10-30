"""Server-side backup management; clients never access SQLite files directly."""

from PySide6 import QtCore, QtWidgets as W


class BackupDialog(W.QDialog):
    def __init__(self, client):
        super().__init__(client)
        self.client = client
        self.rows = []
        self.setWindowTitle("Резервные копии")
        self.resize(1000, 550)
        layout = W.QVBoxLayout(self)
        note = W.QLabel(
            "Копии хранятся на сервере. Перед восстановлением автоматически создаётся страховочная копия. После восстановления все пользователи должны войти снова."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = W.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["Создана (местное время)", "Размер", "Файл"]
        )
        self.table.setSelectionBehavior(
            W.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(W.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        bar = W.QHBoxLayout()
        layout.addLayout(bar)
        for title, fn, admin in [
            ("Создать копию", self.create, False),
            ("Обновить", self.refresh, False),
            ("Удалить", self.delete, True),
            ("Восстановить", self.restore, True),
        ]:
            button = W.QPushButton(title)
            if title == "Удалить":
                button.setProperty("role", "danger")
            elif title == "Создать копию":
                button.setProperty("role", "accent")
            button.clicked.connect(lambda checked=False, f=fn: client.safe(f))
            bar.addWidget(button)
            if admin:
                button.setEnabled(bool(client.current_user.get("is_admin")))
        close = W.QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        bar.addWidget(close)
        self.refresh()

    def refresh(self):
        self.rows = self.client.api("/backups")
        self.table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            stamp = QtCore.QDateTime.fromString(
                row["created_at"], QtCore.Qt.DateFormat.ISODateWithMs
            )
            if not stamp.isValid():
                stamp = QtCore.QDateTime.fromString(
                    row["created_at"], QtCore.Qt.DateFormat.ISODate
                )
            for j, value in enumerate(
                [
                    stamp.toLocalTime().toString("dd.MM.yyyy HH:mm:ss"),
                    f"{row['size'] / 1024:.1f} КБ",
                    row["filename"],
                ]
            ):
                self.table.setItem(i, j, W.QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def selected(self):
        index = self.table.currentRow()
        if index < 0:
            raise ValueError("Выберите резервную копию")
        return self.rows[index]["filename"]

    def create(self):
        self.client.api("/backup", {})
        self.refresh()

    def delete(self):
        filename = self.selected()
        if (
            W.QMessageBox.question(
                self, "Удаление копии", "Удалить без возможности отмены?\n" + filename
            )
            != W.QMessageBox.StandardButton.Yes
        ):
            return
        self.client.api("/backups/delete", {"filename": filename, "confirm": True})
        self.refresh()

    def restore(self):
        filename = self.selected()
        if (
            W.QMessageBox.warning(
                self,
                "Восстановление базы",
                "Текущие данные будут заменены содержимым копии:\n"
                + filename
                + "\nВсе сеансы входа завершатся. Продолжить?",
                W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.No,
                W.QMessageBox.StandardButton.No,
            )
            != W.QMessageBox.StandardButton.Yes
        ):
            return
        result = self.client.api(
            "/backups/restore", {"filename": filename, "confirm": True}
        )
        self.client.token = ""
        self.client.current_user = {}
        self.client.rows = []
        self.client.stock_rows = []
        self.client.sid = None
        self.client.quick.setChecked(False)
        self.client.populate()
        for name, button in self.client.buttons.items():
            if name not in ("Вход", "Подключение"):
                button.setEnabled(False)
        self.client.user_label.setText("Требуется повторный вход")
        W.QMessageBox.information(
            self,
            "База восстановлена",
            "Страховочная копия: "
            + result["safety_backup"]
            + "\nВойдите в программу снова.",
        )
        self.accept()
