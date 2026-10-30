"""Readable audit entries and backwards-compatible document snapshots."""

import json
from .quantities import text
from .security import PERMISSIONS

ACTION_NAMES = {
    "setup": "Первичная настройка",
    "allocate": "Выдача имущества",
    "move": "Перемещение имущества",
    "return": "Возврат на Нулевой склад",
    "batch-transfer": "Групповое перемещение",
    "import": "Импорт из 1С",
    "user.save": "Изменение пользователя",
    "labels.pdf": "Формирование этикеток",
    "backup.delete": "Удаление резервной копии",
    "backup.restore": "Восстановление базы",
    "backup.create": "Создание резервной копии",
}


def document_lines(store, document_id):
    rows = store.read(
        """SELECT l.*,i.name AS item_name,i.unit AS item_unit FROM lines l
        LEFT JOIN assets a ON a.id=l.asset_id LEFT JOIN items i ON i.id=a.item_id
        WHERE l.document_id=? ORDER BY l.rowid""",
        (document_id,),
    )
    for row in rows:
        for field in ("before_json", "after_json"):
            if not row[field]:
                continue
            snap = json.loads(row[field])
            if not snap.get("name"):
                snap["name"] = row["item_name"] or "Наименование не найдено"
            if not snap.get("unit"):
                snap["unit"] = row["item_unit"] or ""
            row[field] = json.dumps(snap, ensure_ascii=False)
        row.pop("item_name", None)
        row.pop("item_unit", None)
    return rows


def issued_lines(lines):
    parsed = [
        (
            json.loads(r["before_json"]) if r.get("before_json") else {},
            json.loads(r["after_json"]),
        )
        for r in lines
    ]
    sources = {
        after["item_id"]: before.get("location_name", "")
        for before, after in parsed
        if before
        and before.get("location") == after.get("location")
        and before.get("quantity_decimal") != after.get("quantity_decimal")
    }
    result = []
    for before, after in parsed:
        if (
            before
            and before.get("location") == after.get("location")
            and before.get("quantity_decimal") != after.get("quantity_decimal")
        ):
            continue
        result.append(
            {
                "number": after.get("number", ""),
                "name": after.get("name", "Наименование не найдено"),
                "quantity": text(
                    after.get("quantity_decimal", after.get("quantity", 1))
                ),
                "unit": after.get("unit", ""),
                "source": before.get("location_name")
                or sources.get(after.get("item_id"))
                or "Нулевой склад",
                "destination": after.get("location_name", ""),
            }
        )
    return result


def audit_entries(store):
    users = {r["id"]: r["name"] for r in store.read("SELECT id,name FROM users")}
    locations = {r["id"]: r for r in store.locations()}
    assets = {r["id"]: r for r in store.assets()}
    items = {r["id"]: r for r in store.read("SELECT id,name,unit FROM items")}
    sessions = {r["id"]: r["name"] for r in store.read("SELECT id,name FROM sessions")}

    def place(ident):
        row = locations.get(ident)
        if not row:
            return "Неизвестное место" if ident else "Не указано"
        parent = locations.get(row.get("parent"))
        return (parent["name"] + " / " if parent else "") + row["name"]

    result = []
    for row in store.read("SELECT * FROM audit ORDER BY at DESC"):
        try:
            p = json.loads(row["data"])
        except (ValueError, TypeError):
            p = {}
        action = row["action"]
        label = ACTION_NAMES.get(action, "Действие системы")
        summary = ""
        if action in ("allocate", "move", "return", "batch-transfer"):
            doc = p.get("document_id")
            if doc:
                lines = issued_lines(document_lines(store, doc))
                summary = "; ".join(
                    f"{r['name']} · {r['number']} · {r['quantity']} {r['unit']}: {r['source']} → {r['destination']}"
                    for r in lines
                )
            else:
                item = items.get(p.get("item_id"), {})
                selected = [
                    assets.get(a.get("id"), {})
                    for a in p.get("assets", [])
                    if isinstance(a, dict)
                ]
                names = ", ".join(
                    (a.get("name", "") + " · " + a.get("number", "")).strip(" ·")
                    for a in selected
                )
                summary = (
                    item.get("name")
                    or names
                    or f"Групповая операция: {len(p.get('lines', []))} позиций"
                )
                if "quantity" in p:
                    summary += f" · {p['quantity']} {item.get('unit', '')}"
                summary += (
                    ": "
                    + place(p.get("source") or "zero")
                    + " → "
                    + place(p.get("destination"))
                )
            if p.get("number"):
                summary += " · Документ № " + str(p["number"])
            if p.get("comment"):
                summary += " · " + str(p["comment"])
        elif action == "import":
            summary = "Файл: " + str(p.get("filename", "не указан"))
            if p.get("result"):
                summary += f" · Позиций: {p['result'].get('positions', '—')}"
            if p.get("excluded_rows"):
                summary += " · Исключены строки: " + ", ".join(
                    map(str, p["excluded_rows"])
                )
        elif action == "user.save":
            summary = (
                "Пользователь: "
                + str(p.get("name", ""))
                + " · "
                + ("Активен" if p.get("active", True) else "Отключён")
                + " · Разрешения: "
                + ", ".join(
                    PERMISSIONS.get(key, key) for key in p.get("permissions", [])
                )
            )
        elif action.startswith("catalog.") or action == "location":
            label = "Изменение справочника"
            if ".create:" in action or action == "location":
                label = "Создание записи справочника"
            elif ".archive:" in action:
                label = "Архивирование записи"
            elif ".restore:" in action:
                label = "Восстановление записи справочника"
            before = p.get("before", {})
            after = p.get("after", {})
            summary = str(
                p.get("name")
                or after.get("name")
                or before.get("name")
                or "Запись справочника"
            )
            if (
                before.get("name")
                and after.get("name")
                and before["name"] != after["name"]
            ):
                summary = before["name"] + " → " + after["name"]
            if p.get("details"):
                summary += " · " + str(p["details"])
        elif action.startswith(("session.", "finding:")):
            kind = action.split(":")[0]
            label = {
                "session.start": "Начало инвентаризации",
                "session.finish": "Завершение инвентаризации",
                "session.check": "Проверка имущества",
                "session.scan": "Сканирование имущества",
            }.get(kind, "Регистрация находки")
            sid = action.split(":", 1)[1] if ":" in action else None
            summary = p.get("name") or sessions.get(sid, "Инвентаризация")
            asset = assets.get(p.get("asset_id"), {})
            if asset:
                summary += " · " + asset["name"] + " · " + asset["number"]
            for key in ("text", "status", "description", "comment"):
                if p.get(key):
                    summary += " · " + str(p[key])
            if p.get("actual"):
                summary += " · " + place(p["actual"])
        elif action == "labels.pdf":
            summary = (
                "Этикетки: "
                + ", ".join(
                    assets.get(a, {}).get("number", "Удалённая карточка")
                    for a in p.get("assets", [])
                )
                + f" · Шаблон {p.get('template', '58x40')} · Копий: {p.get('copies', 1)}"
            )
        elif action.startswith("backup."):
            summary = str(p.get("filename", ""))
        elif action == "setup":
            summary = "Создан пользователь " + str(p.get("name", "Администратор"))
        else:
            summary = "Операция зарегистрирована"
        row["actor_name"] = p.get("_actor_name") or users.get(
            row["user_id"], "Пользователь недоступен"
        )
        row["action_label"] = label
        row["summary"] = summary
        row["data"] = json.dumps(
            {k: v for k, v in p.items() if k != "data"}, ensure_ascii=False
        )
        result.append(row)
    return result
