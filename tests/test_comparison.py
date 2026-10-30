import base64
import os
from fastapi.testclient import TestClient
from aho.server import create_app
from aho.core import uid


def test_comparison_details_and_no_writes(tmp_path):
    app = create_app(tmp_path)
    s = app.state.store
    s.setup('admin', 'test-password-123')
    u = s.user(s.login('Администратор', 'test-password-123')['token'])
    rows = [{'code': 'A', 'name': 'Краска', 'unit': 'л', 'quantity': '1.25', 'rows': [2]},
            {'code': 'B', 'name': 'Стул', 'unit': 'шт', 'quantity': 2, 'rows': [3]}]
    s.mutate(u, uid(), 'import', {}, lambda c: s.import_rows(c, rows, 'old', 'old.csv'))
    old = s.stock()
    raw = 'Код;Номенклатура;Ед. изм.;Количество\nA;Новая краска;кг;2,75\nC;Мыло;л;0,35\n'.encode()
    with TestClient(app) as client:
        token = client.post('/login', json={'name': 'Администратор', 'password': 'test-password-123'}).json()['token']
        response = client.post('/imports/compare', headers={'Authorization': 'Bearer ' + token}, json={
            'filename': 'new.csv', 'data': base64.b64encode(raw).decode(), 'header': 1,
            'mapping': {'code': 0, 'name': 1, 'unit': 2, 'quantity': 3}})
        assert response.status_code == 200, response.text
        result = response.json()
    assert result['new_rows'][0]['name'] == 'Мыло'
    assert result['new_rows'][0]['quantity'] == '0.35'
    assert result['missing_rows'][0]['name'] == 'Стул'
    assert result['changed'][0]['before']['initial'] == '1.25'
    assert s.stock() == old
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6 import QtWidgets as W
    from aho.import_dialog import ImportDialog
    application = W.QApplication.instance() or W.QApplication([])
    # Avoid invoking the file-selection/import initialization.
    owner = ImportDialog.__new__(ImportDialog)
    W.QDialog.__init__(owner)
    dialog = owner.comparison_dialog(result)
    table = dialog.findChild(W.QTableWidget, 'comparison_table')
    assert table.rowCount() == 3
    assert table.item(0, 4).text() == 'Мыло'
    assert table.item(0, 5).text() == '0,35 л'
    assert table.item(1, 3).text() == '1,25 л'
    assert table.item(1, 5).text() == '2,75 кг'
    assert 'наименование' in table.item(1, 1).text()
    assert [table.item(i, 0).background().color().name() for i in range(3)] == ['#d9f2df', '#fff8eb', '#f9dddd']
    dialog.close()
    owner.close()


def test_reimport_preserves_cards_and_rolls_back(tmp_path):
    import pytest
    from aho.core import Store, Conflict
    s = Store(tmp_path)
    s.setup('admin', 'test-password-123')
    u = s.user(s.login('Администратор', 'test-password-123')['token'])
    def load(rows, digest):
        return s.mutate(u, uid(), 'import', {}, lambda c: s.import_rows(c, rows, digest, 'test.csv', update=True))
    def row(code, qty, name='Краска', unit='л'):
        return dict(code=code, name=name, unit=unit, quantity=qty, rows=[2])
    load([row('A', '2.5'), row('B', 1)], 'first')
    item = next(x for x in s.stock() if x['code'] == 'A')
    loc = s.mutate(u, uid(), 'location', {}, lambda c: s.add_location(c, {'name': 'Склад'}))['id']
    p = {'item_id': item['id'], 'quantity': '1.5', 'suffixes': ['-1'], 'destination': loc, 'date': '2026-10-29'}
    s.mutate(u, uid(), 'allocate', p, lambda c: s.movement(c, u['id'], p, True))
    card = s.assets()[0]
    load([row('A', '3.75', 'Краска новая'), row('C', '0.1')], 'second')
    updated = next(x for x in s.stock() if x['code'] == 'A')
    assert updated['id'] == item['id'] and updated['unassigned'] == '2.25'
    assert s.assets()[0]['id'] == card['id'] and s.assets()[0]['number'] == card['number']
    assert {x['code'] for x in s.stock()} == {'A', 'B', 'C'}
    before = s.stock()
    for bad in [row('A', '1.4'), row('A', 4, unit='кг')]:
        with pytest.raises(Conflict):
            load([row('D', 1), bad], uid())
        assert s.stock() == before
    assert len(s.read('SELECT * FROM imports')) == 2
