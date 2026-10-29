"""Settings carried over from older builds."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import tempfile
import unittest
from pathlib import Path

from metalmate.engines import EngineRegistry


class OldBuildTest(unittest.TestCase):
    def test_an_engine_bundled_by_an_older_build_is_forgotten(self):
        """Older builds shipped an engine inside the app. One they registered (with its profiles) is
        removed, and Stockfish stays the engine in use."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = EngineRegistry(Path(tmp) / "engines.json")
            reg.add_engine("Stockfish", ["/opt/homebrew/bin/stockfish"], "homebrew", "stockfish")
            old = reg.add_engine("Forge", ["/Applications/MetalMate.app/Contents/Helpers/forge"], "bundled",
                                 "forge", make_profile=False)
            reg.add_profile("Forge · Balanced", old.id)
            self.assertTrue(reg.forget_bundled())
            self.assertIsNone(reg.find_by_catalog("forge"))
            self.assertTrue(all(p.engine_id != old.id for p in reg.profiles()))
            self.assertIsNotNone(reg.find_by_catalog("stockfish"))
            self.assertFalse(reg.forget_bundled(), "nothing left to forget")


if __name__ == "__main__":
    unittest.main()
