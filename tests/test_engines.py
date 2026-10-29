"""Engine registry, profiles, probing, catalog installs (against a local stand-in for GitHub),
and switching engines mid-game."""
from tests._qt import app  # noqa: F401  (offscreen Qt + scratch data folder; must be first)
import io
import json
import os
import sys
import tarfile
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metalmate import mmchess as chess
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from metalmate import catalog
from metalmate.catalog import CatalogEngine, github
from metalmate.engine import EngineWorker
from metalmate.engines import EngineRegistry, InstallJob, ProbeError, probe

FAKE = str(Path(__file__).with_name("fake_uci.py"))


def fake_cmd(name="FakeFish", *extra):
    return [sys.executable, FAKE, "--name", name, *extra]


def wait_for(predicate, timeout=10.0):
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: predicate() and loop.quit())
    timer.start(20)
    QTimer.singleShot(int(timeout * 1000), loop.quit)
    loop.exec()
    timer.stop()
    return predicate()


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "engines.json"
        self.reg = EngineRegistry(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_engine_makes_a_profile_and_persists(self):
        eng = self.reg.add_engine("Fake", fake_cmd(), uci_name="FakeFish")
        profiles = self.reg.profiles()
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0].engine_id, eng.id)
        again = EngineRegistry(self.path)
        self.assertEqual(again.engine(eng.id).name, "Fake")
        cfg, prof, info = again.config_for(profiles[0].id)
        self.assertEqual(list(cfg.command), fake_cmd())
        self.assertEqual(info.id, eng.id)

    def test_same_path_isnt_added_twice(self):
        a = self.reg.add_engine("Fake", fake_cmd())
        b = self.reg.add_engine("Fake again", fake_cmd())
        self.assertEqual(a.id, b.id)
        self.assertEqual(len(self.reg.engines()), 1)

    def test_removing_an_engine_removes_its_profiles_and_files(self):
        engines_dir = Path(self.tmp.name) / "engines"
        binary = engines_dir / "fake" / "v1" / "fake-engine"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n")
        eng = self.reg.add_engine("Fake", [str(binary)], source="download")
        self.reg.add_profile("Fake · Deep", eng.id, think_time=3)
        self.reg.remove_engine(eng.id, engines_dir)
        self.assertEqual(self.reg.profiles(), [])
        self.assertFalse((engines_dir / "fake").exists())

    def test_defaults_for_stockfish(self):
        sf = "/opt/homebrew/bin/stockfish"
        active = self.reg.ensure_defaults(sf)
        names = [p.name for p in self.reg.profiles()]
        self.assertEqual(names, ["Stockfish · Quick", "Stockfish · Balanced", "Stockfish · Deep"])
        self.assertEqual(self.reg.profile(active).name, "Stockfish · Balanced")
        self.assertIsNone(self.reg.ensure_defaults(sf), "only once")


class ProbeTest(unittest.TestCase):
    def test_probe_reads_name_and_options(self):
        info = probe(fake_cmd("Probey"))
        self.assertEqual(info["name"], "Probey")
        self.assertIn("UCI_Elo", info["options"])

    def test_probe_rejects_non_engines(self):
        with self.assertRaises(ProbeError):
            probe(["/bin/echo", "hello"], timeout=3)
        with self.assertRaises(ProbeError):
            probe(["/nonexistent/engine"])


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class InstallTest(unittest.TestCase):
    """A local web server plays GitHub: a releases API answer plus a .tar.gz holding an engine."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name) / "site"
        (root / "repos" / "test" / "fakefish" / "releases").mkdir(parents=True)
        script = f"#!/bin/sh\nexec '{sys.executable}' '{FAKE}' --name 'Fakefish 2' \"$@\"\n".encode()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name, data in (("fakefish/fakefish-macos-universal", script), ("fakefish/README.md", b"hi")):
                ti = tarfile.TarInfo(name)
                ti.size, ti.mode = len(data), 0o644
                tar.addfile(ti, io.BytesIO(data))
        (root / "dl").mkdir()
        (root / "dl" / "fakefish-macos-universal.tar.gz").write_bytes(buf.getvalue())
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root)))
        port = cls.server.server_address[1]
        release = {"tag_name": "v2.0", "assets": [
            {"name": "fakefish-windows.zip", "browser_download_url": "x", "size": 1},
            {"name": "fakefish-macos-universal.tar.gz", "size": len(buf.getvalue()),
             "browser_download_url": f"http://127.0.0.1:{port}/dl/fakefish-macos-universal.tar.gz"}]}
        (root / "repos" / "test" / "fakefish" / "releases" / "latest").write_text(json.dumps(release))
        cls.api = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def test_install_from_a_github_release(self):
        reg = EngineRegistry(Path(self.tmp.name) / "engines.json")
        entry = CatalogEngine("fakefish", "Fakefish", "2", "Tests", 3000, "", "MIT", "",
                              "", (github("test/fakefish", universal=r"macos-universal\.tar\.gz$",
                                          inner=r"fakefish-macos-universal$"),))
        job = InstallJob(entry, reg, Path(self.tmp.name) / "engines", api_base=self.api)
        steps = []
        job.progress.connect(lambda f, t: steps.append(t))
        job.start()
        job.wait(30)
        app.processEvents()  # progress signals are queued to this thread
        ok, message, engine_id = job.result
        self.assertTrue(ok, message)
        eng = reg.engine(engine_id)
        self.assertEqual(eng.uci_name, "Fakefish 2")
        self.assertEqual(eng.source, "download")
        self.assertTrue(os.access(eng.path, os.X_OK))
        self.assertTrue(any("Downloading" in s for s in steps))
        self.assertEqual(len(reg.profiles()), 1)

    def test_no_build_for_this_mac(self):
        reg = EngineRegistry(Path(self.tmp.name) / "e2.json")
        entry = CatalogEngine("x", "X", "1", "", None, "", "", "", "", ())
        job = InstallJob(entry, reg, Path(self.tmp.name) / "engines")
        job.start()
        job.wait(10)
        self.assertFalse(job.result[0])
        self.assertIn("doesn't publish a build", job.result[1])


class CatalogTest(unittest.TestCase):
    def test_catalog_is_well_formed(self):
        ids = [e.id for e in catalog.CATALOG]
        self.assertEqual(len(ids), len(set(ids)))
        installable = [e for e in catalog.CATALOG if e.installers_for("arm64")]
        self.assertGreaterEqual(len(installable), 6)
        self.assertEqual(catalog.CATALOG[0].id, "stockfish")  # the default engine comes first
        # Built-in engines (Forge) have no website; every downloadable one does.
        self.assertTrue(all(e.website.startswith("https://") for e in catalog.CATALOG if not e.bundled))


class SwitchingTest(unittest.TestCase):
    def test_switching_engine_mid_game_keeps_the_moves(self):
        reg = EngineRegistry(Path(tempfile.mkdtemp()) / "engines.json")
        a = reg.add_engine("Alpha", fake_cmd("AlphaFish"))
        b = reg.add_engine("Beta", fake_cmd("BetaFish", "--prefer-last"))
        pa, pb = (reg.profiles()[0].id, reg.profiles()[1].id)
        worker = EngineWorker()
        self.addCleanup(worker.shutdown)
        results = []
        worker.finished.connect(results.append)
        board = chess.Board()
        for san in "e4 e5 Nf3 Nc6 Bb5".split():
            board.push_san(san)
        worker.configure(reg.config_for(pa)[0])
        worker.analyse(1, board, 0.05, 2)
        self.assertTrue(wait_for(lambda: len(results) == 1))
        worker.configure(reg.config_for(pb)[0])
        worker.analyse(2, board, 0.05, 2)
        self.assertTrue(wait_for(lambda: len(results) == 2))
        first, second = results
        self.assertEqual((first.engine, second.engine), ("AlphaFish", "BetaFish"))
        self.assertEqual(second.board.move_stack, board.move_stack, "the new engine got the whole game")
        self.assertNotEqual(first.lines[0].move, second.lines[0].move)


if __name__ == "__main__":
    unittest.main(verbosity=2)
