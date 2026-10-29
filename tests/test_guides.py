"""The guide key: hold to show, press to toggle, or always on."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from metalmate.config import Settings
from metalmate.session import LiveSession



class GuideKeyTest(unittest.TestCase):
    def session(self, mode):
        st = Settings()
        st.guides_mode = mode
        s = LiveSession(st)
        self.addCleanup(s.shutdown)
        s.timer.start(10_000)              # "watching"
        s.board_rect = QRect(100, 100, 400, 400)
        s.profiles.load = lambda _pid: object()  # pretend the board is learned (no "start a new game" note)
        s._sync_overlay()
        return s

    def visible(self, s):
        return s.overlay.isVisible()

    def test_hold_to_show(self):
        s = self.session("peek")
        self.assertFalse(self.visible(s))
        s.guide_key(True)
        self.assertTrue(self.visible(s))
        s.guide_key(False)
        self.assertFalse(self.visible(s))

    def test_press_to_toggle(self):
        s = self.session("toggle")
        self.assertFalse(self.visible(s), "starts hidden")
        s.guide_key(True)
        s.guide_key(False)
        self.assertTrue(self.visible(s), "one press turns them on, letting go keeps them on")
        s.guide_key(True)
        s.guide_key(False)
        self.assertFalse(self.visible(s), "a second press turns them off")

    def test_always_on(self):
        s = self.session("always")
        self.assertTrue(self.visible(s))
        s.guide_key(True)
        s.guide_key(False)
        self.assertFalse(self.visible(s))

    def test_switching_modes_resets_to_that_modes_default(self):
        s = self.session("always")
        s.settings.guides_mode = "toggle"
        s.settings_changed()
        self.assertFalse(self.visible(s))
        s.settings.guides_mode = "always"
        s.settings_changed()
        self.assertTrue(self.visible(s))


if __name__ == "__main__":
    unittest.main(verbosity=2)
