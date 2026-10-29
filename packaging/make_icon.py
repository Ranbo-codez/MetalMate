"""Render the app icon into packaging/MetalMate.icns (uses macOS iconutil)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from metalmate.ui.logo import app_pixmap  # noqa: E402

app = QGuiApplication([])
with tempfile.TemporaryDirectory() as tmp:
    iconset = Path(tmp) / "MetalMate.iconset"
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        app_pixmap(size).save(str(iconset / f"icon_{size}x{size}.png"))
        app_pixmap(size * 2).save(str(iconset / f"icon_{size}x{size}@2x.png"))
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "MetalMate.icns")], check=True)
print(HERE / "MetalMate.icns")
