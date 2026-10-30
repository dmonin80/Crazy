"""Read-only inventory model: one row dictionary, no per-cell widget allocation."""

from PySide6 import QtCore, QtWidgets as W
from .quantities import quantity

NUMERIC = {"quantity", "initial", "unassigned", "returned", "allocated", "available"}


class InventoryModel(QtCore.QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.columns = []

    def replace(self, rows, columns):
        self.beginResetModel()
        self.rows = list(rows)
        self.columns = columns
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key = self.columns[index.column()][0]
        value = row.get(key, 1 if key == "quantity" else "")
        if role == QtCore.Qt.ItemDataRole.UserRole:
            return row["id"]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return (
                str(value)
                if isinstance(value, int) and abs(value) > 2**63 - 1
                else value
            )
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return str(value)
        if role == QtCore.Qt.ItemDataRole.TextAlignmentRole and key in NUMERIC:
            return int(
                QtCore.Qt.AlignmentFlag.AlignRight
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )

    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return (
                self.columns[section][1]
                if orientation == QtCore.Qt.Orientation.Horizontal
                else str(section + 1)
            )


class InventoryProxy(QtCore.QSortFilterProxyModel):
    def lessThan(self, left, right):
        model = self.sourceModel()
        key = model.columns[left.column()][0]
        a = model.data(left)
        b = model.data(right)
        if key in NUMERIC:
            try:
                return quantity(a) < quantity(b)
            except ValueError:
                pass
        return str(a).casefold() < str(b).casefold()


class Cell:
    """Small compatibility accessor for existing read-only UI integrations."""

    def __init__(self, index):
        self.index = index

    def data(self, role):
        return self.index.data(role)

    def text(self):
        return str(self.index.data() or "") if self.index.data() != 0 else "0"


class InventoryTable(W.QTableView):
    itemSelectionChanged = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = InventoryModel(self)
        self.proxy = InventoryProxy(self)
        self.proxy.setSourceModel(self.source)
        self.setModel(self.proxy)
        self.selectionModel().selectionChanged.connect(
            lambda *_: self.itemSelectionChanged.emit()
        )

    def replace(self, rows, columns):
        self.source.replace(rows, columns)

    def rowCount(self):
        return self.proxy.rowCount()

    def columnCount(self):
        return self.proxy.columnCount()

    def item(self, row, col):
        index = self.proxy.index(row, col)
        return Cell(index) if index.isValid() else None

    def horizontalHeaderItem(self, col):
        return W.QTableWidgetItem(self.source.columns[col][1])

    def sortItems(self, col, order=QtCore.Qt.SortOrder.AscendingOrder):
        self.sortByColumn(col, order)

    def visualItemRect(self, item):
        return self.visualRect(item.index)

    def setCurrentCell(self, row, col):
        self.setCurrentIndex(self.proxy.index(row, col))
