"""Exit 0 if pinned runtime requirements are installed. No network required."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys
for line in (Path(__file__).resolve().parent / 'requirements.txt').read_text('utf-8').splitlines():
    if not line.strip() or line.startswith('#'):
        continue
    package, expected = line.strip().split('==', 1)
    try:
        if version(package) != expected:
            raise SystemExit(1)
    except PackageNotFoundError:
        raise SystemExit(1)
# Check actual DLL/module importability as well as metadata.
import fastapi, uvicorn, httpx, openpyxl, qrcode, reportlab
from PySide6 import QtWidgets
sys.exit(0)
