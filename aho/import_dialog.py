"""Resizable import wizard with real columns, preview and explicit validation."""
import base64
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets as W

from .importer import FIELDS


class ImportDialog(W.QDialog):
    def __init__(self, client, path):
        super().__init__(client)
        self.client = client
        self.path = Path(path)
        from .limits import MAX_FILE_BYTES
        if self.path.stat().st_size>MAX_FILE_BYTES:raise ValueError('Файл больше 20 МБ. Разделите выгрузку на части.')
        self.data = base64.b64encode(self.path.read_bytes()).decode()
        self.excluded = set()
        self.validated = None
        self.result = None
        self.loading = False
        self.setWindowTitle('Импорт выгрузки 1С — выбор колонок и проверка')
        self.resize(1180, 780)
        self.setMinimumSize(820, 540)
        layout = W.QVBoxLayout(self)
        filename = W.QLabel(self.path.name)
        filename.setStyleSheet('font-size:17px;font-weight:600;color:#16324F')
        layout.addWidget(filename)
        self.steps=W.QLabel('1. Файл  →  2. Колонки  →  3. Проверка  →  4. Изменения  →  5. Импорт')
        self.steps.setStyleSheet('padding:10px;background:#F3F6FA;font-weight:600;color:#16324F');layout.addWidget(self.steps)
        note = W.QLabel('Проверьте лист и строку заголовков. Названия и коды сохраняются как в исходном файле. Дробные количества принимаются без округления; пустое количество требует уточнения.')
        note.setWordWrap(True)
        layout.addWidget(note)
        controls = W.QHBoxLayout()
        layout.addLayout(controls)
        self.sheet = W.QComboBox()
        self.header = W.QSpinBox(); self.header.setRange(1, 1000000)
        controls.addWidget(W.QLabel('Лист:')); controls.addWidget(self.sheet, 1)
        controls.addWidget(W.QLabel('Строка заголовков:')); controls.addWidget(self.header)
        self.encoding = W.QComboBox()
        for item in ('utf-8-sig', 'cp1251', 'utf-16'):
            self.encoding.addItem(item)
        self.delimiter = W.QComboBox()
        for label, value in [('Точка с запятой ;', ';'), ('Запятая ,', ','), ('Табуляция', '\t')]:
            self.delimiter.addItem(label, value)
        if self.path.suffix.casefold() == '.csv':
            controls.addWidget(W.QLabel('Кодировка:')); controls.addWidget(self.encoding)
            controls.addWidget(self.delimiter)
        else:
            self.encoding.hide(); self.delimiter.hide()
        mapping_form = W.QGridLayout()
        layout.addLayout(mapping_form)
        self.mapping = {}
        for row, (field, label) in enumerate(FIELDS.items()):
            combo = W.QComboBox()
            combo.setMinimumContentsLength(35)
            combo.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.mapping[field] = combo
            mapping_form.addWidget(W.QLabel(label + ':'), row // 2, (row % 2) * 2)
            mapping_form.addWidget(combo, row // 2, (row % 2) * 2 + 1)
            combo.currentIndexChanged.connect(self.invalidate)
        self.merge = W.QCheckBox('Объединить количества одинаковых кодов, только если совпадают наименование и единица измерения')
        self.merge.stateChanged.connect(self.invalidate)
        layout.addWidget(self.merge)
        self.summary = W.QLabel('Чтение структуры файла…')
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.tabs = W.QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.source = self.make_table()
        self.accepted_rows = self.make_table()
        self.issues = self.make_table()
        self.tabs.addTab(self.source, 'Исходные строки (первые 30)')
        self.tabs.addTab(self.accepted_rows, 'Подготовленные позиции (первые 100)')
        self.tabs.addTab(self.issues, 'Ошибки и предупреждения')
        bar = W.QHBoxLayout()
        layout.addLayout(bar)
        self.check_button = W.QPushButton('3. Проверить данные')
        self.exclude_button = W.QPushButton('Исключить отмеченные строки')
        self.undo_button = W.QPushButton('Вернуть исключённые')
        self.compare_button = W.QPushButton('4. Сравнить с базой')
        self.import_button = W.QPushButton('5. Импортировать')
        self.import_button.setEnabled(False)
        cancel = W.QPushButton('Закрыть')
        for button in (self.check_button, self.exclude_button, self.undo_button, self.compare_button, self.import_button, cancel):
            bar.addWidget(button)
        self.check_button.clicked.connect(lambda: self.safe(self.validate))
        self.exclude_button.clicked.connect(lambda: self.safe(self.exclude_checked))
        self.undo_button.clicked.connect(lambda: self.safe(self.undo_exclusions))
        self.compare_button.clicked.connect(lambda: self.safe(self.compare))
        self.import_button.clicked.connect(lambda: self.safe(self.commit))
        cancel.clicked.connect(self.reject)
        self.sheet.currentTextChanged.connect(lambda _: self.changed_sheet())
        self.header.valueChanged.connect(lambda _: self.changed_header())
        self.encoding.currentTextChanged.connect(lambda _: self.changed_sheet())
        self.delimiter.currentIndexChanged.connect(lambda _: self.changed_sheet())
        self.safe(lambda: self.inspect(auto_sheet=True))

    @staticmethod
    def make_table():
        table = W.QTableWidget()
        table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
        return table

    @staticmethod
    def fill(table, headings, rows):
        table.clear(); table.setColumnCount(len(headings)); table.setHorizontalHeaderLabels(headings)
        table.setRowCount(len(rows))
        for n, values in enumerate(rows):
            for col, value in enumerate(values):
                item = W.QTableWidgetItem('' if value is None else str(value))
                item.setToolTip(item.text())
                table.setItem(n, col, item)
        table.resizeColumnsToContents()
        for col in range(len(headings)):
            table.setColumnWidth(col, min(380, max(90, table.columnWidth(col))))

    def safe(self, fn):
        try:
            fn()
        except Exception as exc:
            self.validated = None
            self.import_button.setEnabled(False)
            self.summary.setText(str(exc))
            self.summary.setStyleSheet('color:#DC2626')

    def basic(self):
        return {'filename': self.path.name, 'data': self.data,
                'encoding': self.encoding.currentText(), 'delimiter': self.delimiter.currentData()}

    def payload(self):
        mapping = {key: combo.currentData() for key, combo in self.mapping.items()}
        if any(value is None for value in mapping.values()) or len(set(mapping.values())) != 4:
            raise ValueError('Выберите четыре разные колонки по заголовкам. Если в файле нет кода или единицы измерения, выберите исходную выгрузку 1С.')
        return dict(self.basic(), sheet=self.sheet.currentText(), header=self.header.value(),
                    mapping=mapping, merge=self.merge.isChecked(), excluded_rows=sorted(self.excluded))

    def invalidate(self, *_):
        if self.loading:
            return
        self.validated = None
        self.import_button.setEnabled(False)
        self.summary.setStyleSheet('')
        self.summary.setText('Настройки изменены. Нажмите «Проверить данные» перед импортом.')

    def changed_sheet(self):
        if not self.loading:
            self.excluded.clear()
            self.safe(self.inspect)

    def changed_header(self):
        if not self.loading:
            self.excluded.clear()
            self.safe(lambda: self.inspect(header=self.header.value()))

    def inspect(self, auto_sheet=False, header=None):
        self.invalidate()
        p = self.basic()
        if not auto_sheet and self.sheet.currentText():
            p['sheet'] = self.sheet.currentText()
        if header is not None:
            p['header'] = header
        info = self.client.api('/imports/inspect', p)
        self.loading = True
        try:
            self.sheet.clear(); self.sheet.addItems(info['sheets']); self.sheet.setCurrentText(info['sheet'])
            self.header.setMaximum(max(1, info['row_count'])); self.header.setValue(info['header'])
            for field, combo in self.mapping.items():
                combo.clear(); combo.addItem('— выберите колонку —', None)
                for column in info['columns']:
                    label = f"{column['letter']} ({column['index']+1}) — {column['heading'] or '(без заголовка)'}"
                    combo.addItem(label, column['index'])
                if field in info['mapping']:
                    combo.setCurrentIndex(combo.findData(info['mapping'][field]))
            headings = [f"{c['letter']} — {c['heading']}" for c in info['columns']]
            self.fill(self.source, headings, [r['values'] for r in info['sample_rows']])
            self.source.setVerticalHeaderLabels([str(r['row']) for r in info['sample_rows']])
            for field, index in info['mapping'].items():
                for row in range(self.source.rowCount()):
                    cell = self.source.item(row, index)
                    if cell:
                        cell.setBackground(QtGui.QColor('#e8f3ff'))
        finally:
            self.loading = False
        if len(info['mapping']) == 4:
            self.validate()
        else:
            missing = ', '.join(FIELDS[key] for key in FIELDS if key not in info['mapping'])
            self.summary.setText('Не распознаны поля: ' + missing + '. Укажите соответствующие колонки или выберите выгрузку 1С.')

    def validate(self):
        p = self.payload()
        result = self.client.api('/imports/preview', p)
        self.result = result
        self.validated = p if not result['errors'] else None
        self.import_button.setEnabled(self.validated is not None)
        self.summary.setStyleSheet('color:#DC2626' if result['errors'] else 'color:#0F766E')
        self.summary.setText(f"Позиций: {len(result['rows'])} · Сумма количеств: {result['units']} · Ошибок: {len(result['errors'])} · Повторов кодов: {len(result['duplicates'])} · Исключено: {len(result['excluded'])} · Служебных строк пропущено: {len(result['skipped'])}. " + ('Исправьте настройки или явно исключите неподходящие строки.' if result['errors'] else 'Данные прошли проверку.'))
        self.fill(self.accepted_rows, ['Строки файла', 'Номенклатура', 'Код', 'Единица измерения', 'Количество'],
                  [[', '.join(map(str, r['rows'])), r['name'], r['code'], r['unit'], r['quantity']] for r in result['rows'][:100]])
        all_issues = [(True, e) for e in result['errors']] + [(False, e) for e in result['warnings']]
        self.fill(self.issues, ['Исключить', 'Строка', 'Ячейка', 'Поле', 'Значение', 'Причина'],
                  [['', e.get('row'), e.get('cell'), e.get('field'), e.get('value'), e['reason']] for _, e in all_issues])
        for index, (is_error, error) in enumerate(all_issues):
            item = self.issues.item(index, 0)
            if is_error and error.get('row') is not None:
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.CheckState.Unchecked)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, error['row'])
        self.issues.setColumnWidth(5, 420)
        if result['errors']:
            self.tabs.setCurrentWidget(self.issues)
        else:
            self.tabs.setCurrentWidget(self.accepted_rows)
        self.undo_button.setEnabled(bool(self.excluded))

    def exclude_checked(self):
        selected = set()
        for row in range(self.issues.rowCount()):
            item = self.issues.item(row, 0)
            if item.checkState() == QtCore.Qt.CheckState.Checked and item.data(QtCore.Qt.ItemDataRole.UserRole) is not None:
                selected.add(item.data(QtCore.Qt.ItemDataRole.UserRole))
        if not selected:
            raise ValueError('Отметьте флажками строки ошибок, которые нужно исключить. Данные этих строк не попадут в начальные остатки.')
        if W.QMessageBox.question(self, 'Исключение строк',
                'Исключить строки ' + ', '.join(map(str, sorted(selected))) + '?\nОстатки по ним не будут созданы. Исходный файл останется без изменений.') != W.QMessageBox.StandardButton.Yes:
            return
        self.excluded.update(selected)
        self.validate()

    def undo_exclusions(self):
        self.excluded.clear()
        self.validate()

    def commit(self):
        if self.validated is None:
            raise ValueError('Сначала проверьте данные')
        comparison=self.client.api('/imports/compare',self.validated)
        message = f"Новых позиций: {len(comparison['new'])}. Изменений: {len(comparison['changed'])}. Отсутствует в файле: {len(comparison['missing'])}.\nЗагрузка выгрузки: {len(self.result['rows'])} позиций, {self.result['units']} единиц."
        if self.excluded:
            message += '\nИсключены строки: ' + ', '.join(map(str, sorted(self.excluded))) + '. Остатки по ним не создаются.'
        if self.result['duplicates']:
            message += f"\nБудут объединены повторные строки: {len(self.result['duplicates'])}."
        message += '\nНовые коды будут добавлены, существующие — обновлены по коду. Количество заменяется значением из файла, а не суммируется.\nКарточки, перемещения и история сохраняются. Отсутствующие в файле позиции не удаляются.\nУменьшение ниже количества созданных карточек и смена единицы при наличии карточек блокируются. Перед загрузкой создаётся резервная копия.'
        if W.QMessageBox.question(self, 'Подтвердите импорт', message + '\nПровести импорт?') != W.QMessageBox.StandardButton.Yes:
            return
        self.client.command('/imports/commit', dict(self.validated, update_existing=True))
        self.client.refresh()
        self.accept()

    def compare(self):
        if self.validated is None:
            raise ValueError('Сначала устраните ошибки и проверьте данные')
        result = self.client.api('/imports/compare', self.validated)
        dialog = self.comparison_dialog(result)
        dialog.exec()

    def comparison_dialog(self, result):
        dialog = W.QDialog(self)
        dialog.setWindowTitle('Сравнение выгрузки с базой — без изменения остатков')
        dialog.resize(1250, 650)
        layout = W.QVBoxLayout(dialog)
        label = W.QLabel(('Этот файл уже импортировался. ' if result['same_file'] else '') +
                         'Сравнение не изменяет остатки и карточки. Количество в базе — по исходной загрузке.')
        label.setWordWrap(True)
        layout.addWidget(label)
        legend = W.QLabel('Зелёный — новая позиция; жёлтый — изменённая; красный — отсутствует в выгрузке.')
        layout.addWidget(legend)
        table = self.make_table()
        table.setObjectName('comparison_table')
        table.setAlternatingRowColors(False)
        layout.addWidget(table)
        rows, colors = [], []
        def amount(row, key):
            return f"{str(row[key]).replace('.', ',')} {row['unit']}"
        for row in result['new_rows']:
            rows.append([row['code'], 'Новая позиция', '', '', row['name'], amount(row, 'quantity')])
            colors.append('#d9f2df')
        for change in result['changed']:
            before, after = change['before'], change['after']
            fields = [title for key, title in [('name', 'наименование'), ('unit', 'ед. изм.'), ('quantity', 'количество')]
                      if before['initial' if key == 'quantity' else key] != after[key]]
            rows.append([change['code'], 'Изменено: ' + ', '.join(fields), before['name'],
                         amount(before, 'initial'), after['name'], amount(after, 'quantity')])
            colors.append('#FFF8EB')
        for row in result['missing_rows']:
            rows.append([row['code'], 'Отсутствует в выгрузке', row['name'], amount(row, 'initial'), '', ''])
            colors.append('#f9dddd')
        self.fill(table, ['Код', 'Различие', 'Наименование в базе', 'Количество в базе',
                          'Наименование в выгрузке', 'Количество в выгрузке'], rows)
        for index, color in enumerate(colors):
            for column in range(table.columnCount()):
                item = table.item(index, column)
                item.setBackground(QtGui.QColor(color))
                item.setForeground(QtGui.QColor('#172b3a'))
        table.setWordWrap(True)
        table.setColumnWidth(2, 260)
        table.setColumnWidth(4, 260)
        table.resizeRowsToContents()
        if not rows:
            layout.addWidget(W.QLabel('Различий не обнаружено.'))
        close = W.QPushButton('Закрыть')
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        return dialog
