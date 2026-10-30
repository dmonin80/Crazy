"""Document journal, line details and a printable transfer form."""

import html
from PySide6 import QtWidgets as W


class DocumentsDialog(W.QDialog):
    def __init__(self, client):
        super().__init__(client)
        self.client = client
        self.setWindowTitle("Документы движения имущества")
        self.resize(1100, 650)
        self.rows = client.api("/documents")
        layout = W.QVBoxLayout(self)
        self.search = W.QLineEdit()
        self.search.setPlaceholderText("Поиск по номеру, дате, автору и комментарию")
        layout.addWidget(self.search)
        self.table = W.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Дата", "Номер", "Операция", "Автор", "Комментарий"]
        )
        self.table.setSelectionBehavior(
            W.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.search.textChanged.connect(self.populate)
        bar = W.QHBoxLayout()
        layout.addLayout(bar)
        for caption, fn in [
            ("Состав документа", self.details),
            ("Печатная форма PDF", self.pdf),
        ]:
            button = W.QPushButton(caption)
            button.clicked.connect(lambda checked=False, f=fn: client.safe(f))
            bar.addWidget(button)
        close = W.QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        self.populate()

    def populate(self, *_):
        query = self.search.text().casefold()
        self.visible = [
            r
            for r in self.rows
            if query in " ".join(str(v) for v in r.values()).casefold()
        ]
        self.table.setRowCount(len(self.visible))
        names = {
            "allocate": "Распределение",
            "move": "Перемещение",
            "batch": "Групповая операция",
        }
        for i, row in enumerate(self.visible):
            for j, key in enumerate(("date", "number", "kind", "author", "comment")):
                self.table.setItem(
                    i, j, W.QTableWidgetItem(names.get(row[key], row[key]))
                )
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def selected(self):
        i = self.table.currentRow()
        if i < 0:
            raise ValueError("Выберите документ")
        row = self.visible[i]
        return row, self.client.api("/documents/" + row["id"])

    def content(self):
        row, lines = self.selected()
        esc = lambda value: html.escape(str(value))
        cells = []
        from .history import issued_lines

        for line in issued_lines(lines):
            cells.append(
                "<tr>"
                + "".join(
                    "<td>" + esc(v) + "</td>"
                    for v in [
                        line["number"],
                        line["name"],
                        line["quantity"],
                        line["unit"],
                        line["source"],
                        line["destination"],
                    ]
                )
                + "</tr>"
            )
        return (
            "<h1>Движение имущества</h1><p>Документ "
            + esc(row["number"] or row["id"])
            + " от "
            + esc(row["date"])
            + "</p><p>Автор: "
            + esc(row["author"])
            + '</p><table border="1" cellspacing="0" cellpadding="6"><tr><th>Номер</th><th>Наименование</th><th>Количество выдано</th><th>Единица измерения</th><th>Откуда</th><th>Куда</th></tr>'
            + "".join(cells)
            + "</table><p>"
            + esc(row["comment"])
            + "</p><p>Передал: ____________________ &nbsp; Принял: ____________________</p>"
        )

    def details(self):
        content = self.content()
        dialog = W.QDialog(self)
        dialog.setWindowTitle("Состав документа")
        dialog.resize(900, 600)
        layout = W.QVBoxLayout(dialog)
        view = W.QTextBrowser()
        view.setHtml(content)
        layout.addWidget(view)
        bar = W.QHBoxLayout()
        layout.addLayout(bar)
        for caption, fn in [
            ("Печать", lambda: self.print_content(content)),
            ("Сохранить PDF", lambda: self.save_pdf(content)),
        ]:
            button = W.QPushButton(caption)
            button.clicked.connect(lambda checked=False, f=fn: self.client.safe(f))
            bar.addWidget(button)
            button.setEnabled(
                bool(
                    self.client.current_user.get("is_admin")
                    or "export" in self.client.current_user.get("permissions", [])
                )
            )
        close = W.QPushButton("Закрыть")
        close.clicked.connect(dialog.accept)
        bar.addWidget(close)
        dialog.exec()

    def print_content(self, content):
        from .security import require
        from PySide6 import QtGui, QtPrintSupport

        require(self.client.current_user, "export")
        printer = QtPrintSupport.QPrinter(
            QtPrintSupport.QPrinter.PrinterMode.HighResolution
        )
        printer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.PageSizeId.A4))
        dialog = QtPrintSupport.QPrintDialog(printer, self)
        if dialog.exec() != W.QDialog.DialogCode.Accepted:
            return
        document = QtGui.QTextDocument()
        document.setHtml(content)
        document.print_(printer)

    def pdf(self):
        self.save_pdf(self.content())

    def save_pdf(self, content):
        from .security import require

        require(self.client.current_user, "export")
        path, _ = W.QFileDialog.getSaveFileName(
            self, "Печатная форма", "movement.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        from PySide6 import QtGui

        writer = QtGui.QPdfWriter(path)
        writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.PageSizeId.A4))
        document = QtGui.QTextDocument()
        document.setHtml(content)
        document.print_(writer)
