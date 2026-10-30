"""Run blocking I/O outside Qt's GUI thread with a responsive, guarded UI."""

from PySide6 import QtCore, QtWidgets as W


class Worker(QtCore.QThread):
    completed = QtCore.Signal()

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.value = None
        self.error = None

    def run(self):
        try:
            self.value = self.fn()
        except Exception as exc:
            self.error = exc
        finally:
            self.completed.emit()


def wait_for_io(parent, fn):
    worker = Worker(fn)
    loop = QtCore.QEventLoop()
    progress = W.QProgressDialog("Обмен данными с сервером…", "", 0, 0, parent)
    progress.setWindowTitle("АХО")
    progress.setCancelButton(None)
    progress.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
    progress.setMinimumDuration(350)
    progress.setAutoClose(False)
    worker.completed.connect(loop.quit)
    progress.show()
    worker.start()
    loop.exec()
    worker.wait()
    progress.close()
    progress.deleteLater()
    if worker.error:
        raise worker.error
    return worker.value
