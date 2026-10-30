"""Verify and restore a backup into a disposable database. Never overwrite live data."""

import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from aho.core import Store


def verify(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError("Файл не найден")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source:
        if (
            source.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
            or source.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise ValueError("Проверка целостности или связей не пройдена")
        database = source.execute(
            "SELECT value FROM meta WHERE key='database_uuid'"
        ).fetchone()[0]
        count = source.execute("SELECT count(*) FROM assets").fetchone()[0]
        with TemporaryDirectory(prefix="aho-restore-") as directory:
            with closing(
                sqlite3.connect(Path(directory) / "inventory.sqlite3")
            ) as target:
                source.backup(target)
            restored = Store(directory)
            if (
                restored.read("SELECT value FROM meta WHERE key='database_uuid'")[0][
                    "value"
                ]
                != database
            ):
                raise ValueError("UUID не совпал после восстановления")
            assets = restored.assets()
            stock = restored.stock()
            if len(assets) != count:
                raise ValueError("Количество карточек не совпало")
            if any(
                row["unassigned"] < 0
                for row in stock
                if isinstance(row["unassigned"], int)
            ):
                raise ValueError("Нарушен баланс остатков")
            for asset in assets:
                if (
                    restored.resolve(f"INV1:{database}:{asset['id']}")["number"]
                    != asset["number"]
                ):
                    raise ValueError("Ошибка восстановления QR-ссылки")
    return database, count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup")
    args = parser.parse_args()
    try:
        database, count = verify(args.backup)
    except Exception as exc:
        raise SystemExit("Проверка не пройдена: " + str(exc))
    print("Целостность и пробное восстановление: OK")
    print("UUID базы:", database)
    print("Карточек:", count)


if __name__ == "__main__":
    main()
