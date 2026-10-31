"""Relaunch: the new copy waits for the old one to quit before starting."""
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import macos


class RelaunchTest(unittest.TestCase):
    def test_waits_for_the_old_copy_to_quit(self):
        old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.0)"])
        t = time.monotonic()
        argv = macos.wait_for_previous_instance(["MetalMate", "--after-pid", str(old.pid), "-x"])
        old.wait()
        self.assertGreaterEqual(time.monotonic() - t, 0.8, "it waited for the old copy")
        self.assertEqual(argv, ["MetalMate", "-x"], "the argument is removed before Qt sees it")

    def test_a_normal_launch_does_not_wait(self):
        t = time.monotonic()
        self.assertEqual(macos.wait_for_previous_instance(["MetalMate"]), ["MetalMate"])
        self.assertLess(time.monotonic() - t, 0.1)

    def test_gives_up_if_the_old_copy_never_quits(self):
        old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            t = time.monotonic()
            macos.wait_for_previous_instance(["MetalMate", "--after-pid", str(old.pid)], timeout=0.5)
            self.assertLess(time.monotonic() - t, 2)
        finally:
            old.kill()
            old.wait()


if __name__ == "__main__":
    unittest.main()
