"""Exact decimal quantities, independent of SQLite floating point arithmetic."""
from decimal import Decimal,InvalidOperation,localcontext
import re


def quantity(value,positive=False):
    if isinstance(value,bool) or value is None:raise ValueError('Количество должно быть числом')
    try:
        text=str(value).strip().replace('\u00a0','').replace('\u202f','').replace(' ','').replace(',','.')
        q=Decimal(text)
    except (InvalidOperation,ValueError):raise ValueError('Некорректное количество')
    if not q.is_finite() or q<0 or (positive and q==0):raise ValueError('Количество должно быть положительным' if positive else 'Количество должно быть неотрицательным')
    if q>=Decimal('1e30') or q.as_tuple().exponent < -30 or len(q.as_tuple().digits)>60:
        raise ValueError('Допустимо до 30 знаков в целой и дробной части; значение не округляется')
    return q


def text(value):
    q=value if isinstance(value,Decimal) else quantity(value)
    if not q.is_finite() or q<0:raise ValueError('Некорректное количество')
    if q==0:return '0'
    value=format(q,'f')
    return value.rstrip('0').rstrip('.') if '.' in value else value


def number(value):
    q=value if isinstance(value,Decimal) else quantity(value)
    if not q.is_finite() or q<0:raise ValueError('Некорректное количество')
    return int(q) if q==q.to_integral_value() else text(q)


def total(values):
    with localcontext() as c:
        c.prec=100
        return sum((quantity(v) for v in values),Decimal(0))


def subtract(a,b):
    with localcontext() as c:
        c.prec=100
        return quantity(a)-quantity(b)


def mode(unit,value):
    unit=re.sub(r'[\s.]','',str(unit).casefold())
    pieces={'шт','штука','штуки','штук','ед','единица','компл','комплект','-'}
    q=quantity(value)
    return 'piece' if unit in pieces and q==q.to_integral_value() else 'quantity'


def migrate(store,backup):
    version=store.read("SELECT value FROM meta WHERE key='schema_version'")[0]['value']
    if version=='3':return
    if version!='2':raise ValueError('Неизвестная схема количественного учёта')
    if backup:store.backup()
    with store.transaction() as c:
        if c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]=='3':return
        c.execute("ALTER TABLE items ADD COLUMN initial_decimal TEXT NOT NULL DEFAULT '0'")
        c.execute("ALTER TABLE items ADD COLUMN tracking_mode TEXT NOT NULL DEFAULT 'piece'")
        c.execute("ALTER TABLE assets ADD COLUMN quantity_decimal TEXT NOT NULL DEFAULT '1'")
        for r in c.execute('SELECT id,initial,unit FROM items').fetchall():
            c.execute('UPDATE items SET initial_decimal=?,tracking_mode=? WHERE id=?',(text(r['initial']),mode(r['unit'],r['initial']),r['id']))
        c.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
