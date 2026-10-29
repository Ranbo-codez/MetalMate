"""Import first in every test module: offscreen Qt, one QApplication for all tests, and a
throwaway data folder so tests never touch your real games or settings."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("METALMATE_DATA", tempfile.mkdtemp(prefix="metalmate-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
