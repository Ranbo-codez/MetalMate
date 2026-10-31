"""Entry point: python -m metalmate (or MetalMate.app)."""
from __future__ import annotations

import os
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import macos
from .config import APP_NAME, Settings
from .session import LiveSession
from .ui import theme
from .ui.logo import app_icon, needs_window_icon
from .ui.main_window import MainWindow
from .ui.splash import Splash


def _test_installs(session: LiveSession, log_path: str, quit_app) -> None:
    """Install every Discover engine that has a Mac build, one after another, as the Download button
    does, then write the results and quit."""
    from . import catalog
    from .config import ENGINES_DIR
    from .engines import InstallJob

    entries = [e for e in catalog.CATALOG if e.installers_for()]
    lines: list[str] = []

    def next_one() -> None:
        if not entries:
            with open(log_path, "w") as f:
                f.write("\n".join(lines) + "\n")
            quit_app()
            return
        entry = entries.pop(0)
        job = InstallJob(entry, session.engines, ENGINES_DIR)

        def done(ok: bool, message: str, engine_id: str) -> None:
            lines.append(f"{entry.id}: {'OK' if ok else 'FAIL'} {message}")
            QTimer.singleShot(0, next_one)

        job.finished.connect(done)
        job.start()
        session._test_jobs = getattr(session, "_test_jobs", []) + [job]  # keep it alive

    next_one()


def main() -> None:
    # Started by "Relaunch": let the old copy finish quitting first.
    sys.argv = macos.wait_for_previous_instance(sys.argv)
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(APP_NAME)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.QSS)
    if needs_window_icon():
        app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)  # keeps watching from the menu bar when the window is closed

    settings = Settings.load()
    selftest_log = os.environ.get("METALMATE_SELFTEST")
    splash = None
    if settings.show_splash and not selftest_log:
        splash = Splash()
        splash.start()
        app.processEvents()

    session = LiveSession(settings)
    window = MainWindow(session)
    app.aboutToQuit.connect(window.quit_app)
    # `kill <pid>` (e.g. when updating the app) quits cleanly too. Python only runs signal handlers
    # when it gets control, so give it a moment every half second.
    signal.signal(signal.SIGTERM, lambda *_: window.quit_app())
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(500)

    def reveal() -> None:
        if os.environ.get("METALMATE_TEST_HIDDEN"):  # automated tests: keep the window out of the way
            window.start_watching_if_ready()
            return
        window.show()
        window.raise_()
        window.activateWindow()
        if not settings.onboarding_done and not selftest_log:
            QTimer.singleShot(250, window.run_onboarding)
        else:
            window.start_watching_if_ready()

    if splash is not None:
        splash.finished.connect(reveal)
    else:
        reveal()

    if os.environ.pop("METALMATE_TEST_RELAUNCH", None):  # automated test of the Relaunch button (once:
        QTimer.singleShot(3000, window.relaunch)                # the new copy inherits the environment)
    install_log = os.environ.get("METALMATE_TEST_INSTALL")  # automated test of one-click engine installs
    if install_log:
        QTimer.singleShot(1000, lambda: _test_installs(session, install_log, window.quit_app))

    if selftest_log:
        def write_and_quit(report) -> None:
            with open(selftest_log, "w") as f:
                f.write(("PASS" if report.passed else "FAIL") + "\n" + report.text() + "\n")
            window.quit_app()

        QTimer.singleShot(1000, lambda: window.run_self_test(on_done=write_and_quit))
    app.exec()
    window.quit_app()
