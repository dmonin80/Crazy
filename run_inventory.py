"""Single entry point: local server + desktop client on the same computer."""

import argparse
import sys
from pathlib import Path

from aho.local_runtime import (
    app_root,
    control,
    ensure_local_server,
    run_server_child,
    stop_local_server,
    url,
)


def main():
    parser = argparse.ArgumentParser(
        description="АХО — единый запуск сервера и клиента"
    )
    parser.add_argument(
        "--root", default=str(app_root()), help="Папка программы и данных"
    )
    parser.add_argument("--server-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--stop-server",
        action="store_true",
        help="Корректно остановить локальный сервер",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--local", action="store_true", help="Локальная база: не читать network.json"
    )
    modes.add_argument(
        "--lan-host",
        action="store_true",
        help="Запустить единственный сервер общей базы на этом ПК",
    )
    modes.add_argument(
        "--network-client", action="store_true", help="Запустить только сетевой клиент"
    )
    parser.add_argument("--server-url", help="Адрес сервера для сетевого клиента")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.server_child:
        # Windowed PyInstaller/pythonw processes have no Python standard streams.
        if sys.stdout is None or sys.stderr is None:
            logs = root / "data" / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            log = (logs / "local_server.log").open("a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = log
        run_server_child(root)
        return 0
    if args.stop_server:
        try:
            stopped = stop_local_server(root)
            message = (
                "Локальный сервер остановлен."
                if stopped
                else "Локальный сервер уже остановлен."
            )
            code = 0
        except Exception as exc:
            message = "Не удалось остановить сервер: " + str(exc)
            code = 1
        if sys.stdout:
            print(message)
        elif sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, message, "АХО", 0x10 if code else 0x40
            )
        return code
    if args.lan_host:
        return desktop(root, lan=True)
    if args.local:
        return desktop(root)
    from aho.network import read_network_settings, is_network_path

    try:
        settings = read_network_settings(root)
    except Exception as exc:
        from PySide6 import QtWidgets as W

        _app = W.QApplication(sys.argv[:1])
        W.QMessageBox.critical(None, "Настройки сети", str(exc))
        return 1
    if args.server_url or settings or args.network_client or is_network_path(root):
        return network_desktop(
            root,
            args.server_url or (settings or {}).get("server_url"),
            (settings or {}).get("ca_file"),
        )
    return desktop(root)


def desktop(root, lan=False):
    from PySide6 import QtCore, QtWidgets as W
    from aho.client import Client

    app = W.QApplication(sys.argv[:1])
    app.setApplicationName("АХО — Инвентаризация")
    progress = W.QProgressDialog("Запускается локальный сервер…", "", 0, 0)
    progress.setWindowTitle("АХО — запуск")
    progress.setCancelButton(None)
    progress.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.show()
    app.processEvents()
    try:
        config = ensure_local_server(
            root,
            lan=lan,
            progress=lambda: app.processEvents(
                QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
            ),
        )
        status = control(config, "/local/status")
    except Exception as exc:
        progress.close()
        W.QMessageBox.critical(None, "Ошибка запуска АХО", str(exc))
        return 1
    window = Client(local_url=url(config), settings_root=root)
    window.setWindowTitle(
        "АХО — инвентаризация · "
        + ("СЕРВЕР ОБЩЕЙ БАЗЫ" if lan else "сервер и клиент на этом ПК")
        + " · 0.3.1"
    )
    window.statusBar().showMessage("Локальный сервер запущен · " + url(config))

    def stop_and_exit():
        if (
            W.QMessageBox.question(
                window,
                "Остановить сервер",
                "Остановить локальный сервер и закрыть это окно? Другие открытые окна этой базы потеряют соединение.",
            )
            != W.QMessageBox.StandardButton.Yes
        ):
            return
        try:
            stop_local_server(root)
        except Exception as exc:
            W.QMessageBox.warning(window, "Остановка сервера", str(exc))
            return
        window.close()

    menu = window.menuBar().addMenu("Система")
    menu.addAction("Остановить локальный сервер и выйти", stop_and_exit)
    if lan:
        window.network_label = W.QLabel("Общая база · сетевой сервер: порт 8765")
        window.statusBar().addPermanentWidget(window.network_label)
    enable_periodic_refresh(window)
    window.show()
    progress.close()

    def setup_or_login():
        if not status["setup_required"]:
            window.safe(window.login)
            return
        dialog = W.QDialog(window)
        dialog.setWindowTitle("Первый запуск — администратор")
        dialog.setMinimumWidth(440)
        form = W.QFormLayout(dialog)
        form.addRow(W.QLabel("Создайте администратора для локальной базы."))
        name = W.QLineEdit("Администратор")
        name.setReadOnly(True)
        password = W.QLineEdit()
        password.setEchoMode(W.QLineEdit.EchoMode.Password)
        repeat = W.QLineEdit()
        repeat.setEchoMode(W.QLineEdit.EchoMode.Password)
        form.addRow("Имя:", name)
        form.addRow("Пароль (от 12 символов):", password)
        form.addRow("Повтор пароля:", repeat)
        error = W.QLabel()
        error.setWordWrap(True)
        error.setStyleSheet("color:#ae2020")
        form.addRow(error)
        buttons = W.QDialogButtonBox(
            W.QDialogButtonBox.StandardButton.Ok
            | W.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(W.QDialogButtonBox.StandardButton.Ok).setText("Создать и войти")
        buttons.button(W.QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        form.addRow(buttons)

        def create():
            if not buttons.isEnabled():
                return
            if not name.text().strip():
                error.setText("Укажите имя администратора.")
                return
            if len(password.text()) < 12:
                error.setText("Пароль должен содержать минимум 12 символов.")
                return
            if password.text() != repeat.text():
                error.setText("Пароли не совпадают.")
                return
            buttons.setEnabled(False)
            try:
                if control(config, "/local/status")["setup_required"]:
                    control(
                        config,
                        "/local/setup",
                        {"name": name.text().strip(), "password": password.text()},
                    )
                window.login_with_credentials("Администратор", password.text())
            except Exception as exc:
                error.setText(str(exc))
                buttons.setEnabled(True)
                return
            password.clear()
            repeat.clear()
            dialog.accept()

        buttons.accepted.connect(create)
        buttons.rejected.connect(dialog.reject)
        accepted = dialog.exec()
        password.clear()
        repeat.clear()
        if accepted != W.QDialog.DialogCode.Accepted:
            window.close()

    QtCore.QTimer.singleShot(0, setup_or_login)
    return app.exec()


def network_desktop(root, address=None, ca_file=None):
    from PySide6 import QtCore, QtWidgets as W
    from aho.client import Client
    import httpx

    app = W.QApplication(sys.argv[:1])
    app.setApplicationName("АХО — сетевой клиент")
    if not address:
        address, ok = W.QInputDialog.getText(
            None,
            "Подключение к общей базе",
            "Адрес сервера:",
            text="http://pc00527:8765",
        )
        if not ok:
            return 0
    try:
        from urllib.parse import urlsplit

        parsed = urlsplit(address)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Укажите адрес вида http://pc00527:8765")
        response = httpx.get(
            address.rstrip("/") + "/health",
            timeout=5,
            trust_env=False,
            verify=ca_file or True,
        )
        response.raise_for_status()
        if response.json().get("service") != "aho_inventory":
            raise ValueError("По этому адресу работает другая служба")
    except Exception as exc:
        W.QMessageBox.critical(
            None,
            "Сервер общей базы недоступен",
            str(exc)
            + "\nПроверьте запуск сервера на основном ПК, адрес и доступ к TCP-порту 8765.",
        )
        return 1
    window = Client(settings_root=root, server_url=address.rstrip("/"))
    if ca_file:
        window.settings["ca_file"] = ca_file
    window.setWindowTitle("АХО — общая база · " + address + " · 0.3.1")
    menu = window.menuBar().addMenu("Система")
    menu.addAction(
        "Адрес сервера",
        lambda: W.QMessageBox.information(window, "Общая база", address),
    )
    window.network_label = W.QLabel("Общая база: " + address)
    window.statusBar().addPermanentWidget(window.network_label)
    enable_periodic_refresh(window)
    window.show()
    QtCore.QTimer.singleShot(0, lambda: window.safe(window.login))
    return app.exec()


def enable_periodic_refresh(window):
    from PySide6 import QtCore, QtWidgets as W

    timer = QtCore.QTimer(window)
    seconds = int(window.preferences.value("refresh_seconds", 15))
    timer.setInterval(max(1, seconds) * 1000)
    window.refresh_timer = timer

    def update():
        if window.token and not window._busy and not W.QApplication.activeModalWidget():
            try:
                window.refresh()
            except Exception as exc:
                window.statusBar().showMessage(str(exc))

    timer.timeout.connect(update)
    if seconds:
        timer.start()
    return timer


if __name__ == "__main__":
    raise SystemExit(main())
