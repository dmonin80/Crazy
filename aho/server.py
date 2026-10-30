import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.responses import Response
from .core import Store, Conflict
from .security import require, admin_only, save_user, PERMISSIONS
from .importer import preview, inspect_source
from . import api_models as models
from .security import action_permission


def create_app(root, local_config=None):
    store = Store(root)
    app = FastAPI(title="АХО — учёт имущества", version="0.3.2")
    app.state.store = store

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=409 if isinstance(exc, Conflict) else 400,
            content={"detail": str(exc)},
        )

    @app.exception_handler(PermissionError)
    async def permission_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=403, content={"detail": str(exc)})

    def user(authorization: str = Header(default="")):
        return store.user(authorization.removeprefix("Bearer "))

    def mutation(p, u, action, handler, admin=False):
        if action == "batch-transfer":
            models.validate_command(action, p)
            for line in p.get("lines", []):
                require(u, "allocate" if line.get("kind") == "allocate" else "move")
        else:
            require(u, action_permission(action))
        models.validate_command(action, p)
        return store.mutate(
            u,
            p["request_id"],
            action,
            {k: v for k, v in p.items() if k != "request_id"},
            handler,
            admin,
        )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "version": "0.3.2",
            "service": "aho_inventory",
            "instance_id": local_config["instance_id"] if local_config else None,
            "root_key": local_config.get("root_key") if local_config else None,
        }

    # These routes exist only for the all-in-one loopback server, never for a LAN server.
    if local_config is not None:
        import secrets

        def local_authority(request: Request, x_local_token: str = Header(default="")):
            if request.client is None or request.client.host not in (
                "127.0.0.1",
                "::1",
            ):
                raise PermissionError(
                    "Управление сервером доступно только на компьютере с базой"
                )
            if not secrets.compare_digest(x_local_token, local_config["control_token"]):
                raise PermissionError("Нет прав локального управления")

        @app.get("/local/status", dependencies=[Depends(local_authority)])
        def local_status():
            return {
                "setup_required": not bool(store.read("SELECT 1 FROM users LIMIT 1"))
            }

        @app.post("/local/setup", dependencies=[Depends(local_authority)])
        def local_setup(p: dict):
            name = p.get("name")
            password = p.get("password")
            if (
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(password, str)
            ):
                raise ValueError("Укажите имя и пароль администратора")
            store.setup(name.strip(), password)
            return {"created": True}

        @app.post("/local/shutdown", dependencies=[Depends(local_authority)])
        def local_shutdown():
            callback = getattr(app.state, "local_shutdown", None)
            if callback is None:
                raise Conflict("Завершение сервера пока недоступно")
            callback()
            return {"status": "Завершение после текущих запросов"}

    @app.get("/login/users")
    def login_users():
        return store.read("SELECT name FROM users WHERE active=1 ORDER BY name")

    @app.get("/users")
    def users(u=Depends(user)):
        admin_only(u)
        return {
            "permissions": PERMISSIONS,
            "users": [
                dict(r, permissions=json.loads(r["permissions"]))
                for r in store.read(
                    "SELECT id,name,active,permissions FROM users ORDER BY name"
                )
            ],
        }

    @app.post("/users/save")
    def users_save(p: dict, u=Depends(user)):
        admin_only(u)
        models.validate(models.User, p)
        return save_user(store, u, p)

    @app.post("/logout")
    def logout(u=Depends(user), authorization: str = Header(default="")):
        with store.transaction() as c:
            c.execute(
                "DELETE FROM tokens WHERE hash=?",
                (
                    hashlib.sha256(
                        authorization.removeprefix("Bearer ").encode()
                    ).hexdigest(),
                ),
            )
        return {"ok": True}

    @app.post("/login")
    def login(p: dict):
        models.validate(models.Login, p)
        return store.login(p["name"], p["password"])

    @app.get("/me")
    def me(u=Depends(user)):
        return u

    @app.get("/catalogs")
    def catalogs(u=Depends(user)):
        from .catalogs import list_entries

        return {
            "locations": store.locations(),
            "responsibles": list_entries(store, "responsibles"),
            "suppliers": list_entries(store, "suppliers"),
            "units": [
                r["unit"]
                for r in store.read("SELECT DISTINCT unit FROM items ORDER BY unit")
            ],
        }

    @app.get("/catalogs/{kind}")
    def catalog(kind: str, u=Depends(user)):
        from .catalogs import list_entries

        return list_entries(store, kind)

    @app.post("/catalogs/{kind}")
    def create_catalog(kind: str, p: dict, u=Depends(user)):
        from .catalogs import create_entry

        return mutation(
            p,
            u,
            "catalog.create:" + kind,
            lambda c: store.add_location(c, p)
            if kind == "locations"
            else create_entry(c, kind, p),
            True,
        )

    @app.post("/catalogs/{kind}/{ident}")
    def edit_catalog(kind: str, ident: str, p: dict, u=Depends(user)):
        from .catalogs import update_entry

        result = mutation(
            p,
            u,
            "catalog." + p.get("action", "edit") + ":" + kind + ":" + ident,
            lambda c: update_entry(c, kind, ident, p),
            True,
        )
        return result

    @app.get("/stock")
    def stock(u=Depends(user)):
        return store.stock()

    @app.get("/assets")
    def assets(u=Depends(user)):
        return store.assets()

    @app.get("/overview")
    def overview(u=Depends(user)):
        from contextlib import closing

        with closing(store.connect()) as c:
            c.execute("BEGIN")
            return {"assets": store.assets(c), "stock": store.stock(c), "user": u}

    @app.get("/assets/{asset_id}")
    def asset_detail(asset_id: str, u=Depends(user)):
        result = next((r for r in store.assets() if r["id"] == asset_id), None)
        if result is None:
            raise HTTPException(404, "Карточка не найдена")
        result["database_uuid"] = store.read(
            "SELECT value FROM meta WHERE key='database_uuid'"
        )[0]["value"]
        return result

    @app.get("/documents")
    def documents(u=Depends(user)):
        return store.read(
            "SELECT d.*,u.name AS author FROM documents d JOIN users u ON u.id=d.user_id ORDER BY d.at DESC"
        )

    @app.get("/documents/{document_id}")
    def document_lines(document_id: str, u=Depends(user)):
        return store.read("SELECT * FROM lines WHERE document_id=?", (document_id,))

    @app.get("/locations")
    def locations(u=Depends(user)):
        return store.locations()

    @app.post("/locations")
    def location(p: dict, u=Depends(user)):
        return mutation(p, u, "location", lambda c: store.add_location(c, p), True)

    @app.post("/imports/inspect")
    def inspect_import(p: dict, u=Depends(user)):
        require(u, "import")
        models.validate(models.Import, p)
        raw = base64.b64decode(p["data"], validate=True)
        return inspect_source(
            raw,
            p["filename"],
            p.get("sheet"),
            p.get("header"),
            p.get("encoding", "utf-8-sig"),
            p.get("delimiter", ";"),
        )

    @app.post("/imports/preview")
    def import_preview(p: dict, u=Depends(user)):
        require(u, "import")
        models.validate(models.ImportPreview, p)
        raw = base64.b64decode(p["data"], validate=True)
        return preview(
            raw,
            p["filename"],
            p["mapping"],
            p.get("header", 1),
            p.get("sheet"),
            p.get("encoding", "utf-8-sig"),
            p.get("delimiter", ";"),
            p.get("merge", False),
            p.get("excluded_rows", []),
        )

    @app.post("/imports/commit")
    def import_commit(p: dict, u=Depends(user)):
        result = import_preview(p, u)
        if result["errors"]:
            raise ValueError("Исправьте ошибки предварительной проверки")
        models.validate_command("import", p)
        raw = base64.b64decode(p["data"], validate=True)
        archive = (
            store.root
            / "imports"
            / (result["hash"] + Path(p["filename"]).suffix.lower())
        )

        # Only a new accepted operation needs a backup/archive. Retries use stored results.
        def commit(c):
            archive.write_bytes(raw)
            return store.import_rows(
                c,
                result["rows"],
                result["hash"],
                Path(p["filename"]).name,
                update=p.get("update_existing") is True,
            )

        return store.mutate(
            u,
            p["request_id"],
            "import",
            {k: v for k, v in p.items() if k != "request_id"},
            commit,
            before_mutation=store.backup,
        )

    @app.post("/imports/compare")
    def compare(p: dict, u=Depends(user)):
        result = import_preview(p, u)
        if result["errors"]:
            return result
        old = {r["code"]: r for r in store.stock()}
        new = {r["code"]: r for r in result["rows"]}
        added = sorted(new.keys() - old.keys())
        missing = sorted(old.keys() - new.keys())
        changed = [
            {"code": k, "before": old[k], "after": new[k]}
            for k in sorted(new.keys() & old.keys())
            if (old[k]["name"], old[k]["unit"], old[k]["initial"])
            != (new[k]["name"], new[k]["unit"], new[k]["quantity"])
        ]
        return {
            "new": added,
            "missing": missing,
            "changed": changed,
            "new_rows": [new[k] for k in added],
            "missing_rows": [old[k] for k in missing],
            "same_file": bool(
                store.read("SELECT 1 FROM imports WHERE hash=?", (result["hash"],))
            ),
        }

    @app.post("/allocate")
    def allocate(p: dict, u=Depends(user)):
        return mutation(p, u, "allocate", lambda c: store.movement(c, u["id"], p, True))

    @app.post("/batch-transfer")
    def batch_transfer(p: dict, u=Depends(user)):
        return mutation(
            p, u, "batch-transfer", lambda c: store.batch_movement(c, u["id"], p)
        )

    @app.post("/move")
    def move(p: dict, u=Depends(user)):
        return mutation(
            p,
            u,
            "return" if p.get("destination") == "zero" else "move",
            lambda c: store.movement(c, u["id"], p),
        )

    @app.post("/resolve")
    def resolve(p: dict, u=Depends(user)):
        models.validate(models.Resolve, p)
        return store.resolve(p["text"])

    @app.get("/history/{asset_id}")
    def history(asset_id: str, u=Depends(user)):
        return store.read(
            "SELECT d.*,l.before_json,l.after_json FROM documents d JOIN lines l ON d.id=l.document_id WHERE l.asset_id=? ORDER BY d.at",
            (asset_id,),
        )

    @app.get("/sessions")
    def sessions(u=Depends(user)):
        return store.read("SELECT * FROM sessions ORDER BY at DESC")

    @app.post("/sessions")
    def start(p: dict, u=Depends(user)):
        return mutation(p, u, "session.start", lambda c: store.start_session(c, p))

    @app.get("/sessions/{sid}")
    def checks(sid: str, u=Depends(user)):
        return store.read("SELECT * FROM checks WHERE session_id=?", (sid,))

    @app.post("/sessions/{sid}/check")
    def check(sid: str, p: dict, u=Depends(user)):
        return mutation(
            p, u, "session.check:" + sid, lambda c: store.check(c, u["id"], sid, p)
        )

    @app.post("/sessions/{sid}/scan")
    def scan(sid: str, p: dict, u=Depends(user)):
        return mutation(
            p, u, "session.scan:" + sid, lambda c: store.scan(c, u["id"], sid, p)
        )

    @app.post("/sessions/{sid}/finish")
    def finish(sid: str, p: dict, u=Depends(user)):
        def run(c):
            if not p.get("confirm"):
                raise ValueError(
                    "Подтвердите завершение с непроверенными позициями и расхождениями"
                )
            changed = c.execute(
                "UPDATE sessions SET state='Завершена' WHERE id=? AND state='В работе'",
                (sid,),
            ).rowcount
            if not changed:
                raise Conflict("Сессия уже завершена или отсутствует")
            return {"state": "Завершена"}

        return mutation(p, u, "session.finish:" + sid, run)

    @app.post("/sessions/{sid}/finding")
    def finding(sid: str, p: dict, u=Depends(user)):
        from .core import uid, now

        def run(c):
            if not c.execute(
                "SELECT 1 FROM sessions WHERE id=? AND state='В работе'", (sid,)
            ).fetchone():
                raise Conflict("Сессия закрыта")
            ident = uid()
            c.execute(
                "INSERT INTO findings VALUES(?,?,?,?,?)",
                (ident, sid, p["description"], now(), u["id"]),
            )
            return {"id": ident}

        return mutation(p, u, "finding:" + sid, run)

    @app.get("/audit")
    def audit(u=Depends(user)):
        require(u, "audit")
        return store.read("SELECT * FROM audit ORDER BY at DESC")

    @app.get("/requests/{rid}")
    def request_result(rid: str, u=Depends(user)):
        rows = store.read(
            "SELECT result FROM requests WHERE id=? AND user_id=?", (rid, u["id"])
        )
        if not rows:
            raise HTTPException(404, "Запрос не проведён")
        return json.loads(rows[0]["result"])

    @app.post("/backup")
    def backup(p: dict, u=Depends(user)):
        require(u, "backup")
        return {"filename": store.backup().name}

    @app.get("/backups")
    def backups(u=Depends(user)):
        require(u, "backup")
        return store.list_backups()

    @app.post("/backups/delete")
    def delete_backup(p: dict, u=Depends(user)):
        admin_only(u)
        if p.get("confirm") is not True:
            raise ValueError("Подтвердите удаление")
        return store.delete_backup(p.get("filename"), u)

    @app.post("/backups/restore")
    def restore_backup(p: dict, u=Depends(user)):
        admin_only(u)
        if p.get("confirm") is not True:
            raise ValueError("Подтвердите восстановление")
        return store.restore_backup(p.get("filename"), u)

    @app.post("/labels")
    def labels(p: dict, u=Depends(user)):
        require(u, "labels")
        from .labels import make_pdf

        models.validate(models.Labels, p)
        selected = p["assets"]
        assets = {a["id"]: a for a in store.assets()}
        if not selected or any(a not in assets for a in selected):
            raise ValueError("Выберите существующие карточки")
        db = store.read("SELECT value FROM meta WHERE key='database_uuid'")[0]["value"]
        pdf = make_pdf(
            [assets[a] for a in selected],
            db,
            p.get("template", "58x40"),
            p.get("copies", 1),
            p.get("skip", 0),
        )
        with store.transaction() as c:
            store.audit(
                c,
                u["id"],
                "labels.pdf",
                {
                    "assets": selected,
                    "template": p.get("template", "58x40"),
                    "copies": p.get("copies", 1),
                    "status": "PDF сформирован",
                },
            )
        return Response(pdf, media_type="application/pdf")

    return app


def main():
    parser = argparse.ArgumentParser()
    default = (
        Path(sys.executable).parent / "data"
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent / "data"
    )
    parser.add_argument("--data", default=str(default))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--cert")
    parser.add_argument("--key")
    args = parser.parse_args()
    from .network import require_local_server_root

    require_local_server_root(args.data)
    if args.setup:
        from getpass import getpass

        Store(args.data).setup(
            input("Имя администратора: "), getpass("Пароль (минимум 12 символов): ")
        )
        return
    import uvicorn

    uvicorn.run(
        create_app(args.data),
        host=args.host,
        port=args.port,
        ssl_certfile=args.cert,
        ssl_keyfile=args.key,
    )


if __name__ == "__main__":
    main()
