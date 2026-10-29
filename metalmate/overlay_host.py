"""The on-board guides live in a tiny background helper process.

macOS only lets windows from "accessory" apps (no Dock icon, set up that way at launch) appear on
top of another app's full-screen window. The main app should stay a normal app with a Dock icon
and menus, so the overlay window runs in a helper that the main app drives over a pipe.
If the helper can't run, the overlay falls back to the main process (fine on normal desktops)."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading

from metalmate import mmchess as chess
from PySide6.QtCore import QObject, QRect, Signal

ROLE_ENV = "METALMATE_ROLE"


def apply_message(overlay, msg: dict) -> None:
    from .overlay import Arrow
    op = msg.get("op")
    if op == "board":
        overlay.set_board(QRect(*msg["rect"]), msg["white_bottom"])
    elif op == "suggest":
        arrows = [Arrow(chess.Move.from_uci(a["uci"]), a["color"], a["width"], a["alpha"], a["hint"])
                  for a in msg["arrows"]]
        overlay.set_suggestions(arrows, msg["badge"], msg["eval_cp"], msg["eval_text"], msg["show_eval"])
    elif op == "clear":
        overlay.clear(msg.get("badge", ""))
    elif op == "outline":
        overlay.flash_outline(msg["on"])
    elif op == "opacity":
        overlay.setWindowOpacity(msg["value"])
    elif op == "show":
        overlay.show()
    elif op == "hide":
        overlay.hide()


def host_main() -> None:
    """Entry point of the helper process. In the packaged app it runs from its own small bundle,
    MetalMate.app/Contents/Helpers/MetalMate Guides.app, marked LSUIElement: macOS then registers it
    as a background app from the first instant, so it never shows up (or lingers) in the Dock."""
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    try:  # must happen before the first window exists
        import AppKit
        AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    except Exception:
        pass
    from .overlay import ArrowOverlay
    overlay = ArrowOverlay()

    class IgnoreQuit(QObject):
        """Quit requests aimed at "MetalMate" belong to the main app; the helper ends with its pipe."""

        def eventFilter(self, obj, event) -> bool:
            from PySide6.QtCore import QEvent
            return event.type() == QEvent.Type.Quit

    ignore_quit = IgnoreQuit()
    app.installEventFilter(ignore_quit)

    class Pipe(QObject):
        line = Signal(bytes)
        closed = Signal()

    pipe = Pipe()

    def pump() -> None:
        while True:
            raw = sys.stdin.buffer.readline()
            if not raw:
                break
            pipe.line.emit(raw)
        pipe.closed.emit()

    def handle(raw: bytes) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if msg.get("op") == "quit":
            os._exit(0)
        apply_message(overlay, msg)

    pipe.line.connect(handle)
    pipe.closed.connect(lambda: os._exit(0))  # the main app went away
    threading.Thread(target=pump, daemon=True).start()
    app.exec()
    os._exit(0)


def helper_command() -> list[str]:
    if getattr(sys, "frozen", False):
        helper = os.path.join(os.path.dirname(os.path.dirname(sys.executable)), "Helpers", "MetalMate Guides.app",
                              "Contents", "MacOS", "MetalMate Guides")
        return [helper if os.path.exists(helper) else sys.executable]
    return [sys.executable, "-m", "metalmate.overlay_host"]


class OverlayClient:
    """Same interface as ArrowOverlay, drawn by the helper process.

    Messages go to the helper from a writer thread, so a slow or stuck helper can never freeze the
    app. If the helper dies it is started again and given the current board and arrows; only if
    that keeps failing do the guides fall back to the main process (which can't appear over
    full-screen apps)."""

    MAX_RESTARTS = 5

    def __init__(self) -> None:
        self._visible = False
        self._opacity = 1.0
        self._last: dict[str, dict] = {}
        self._local = None
        self._lock = threading.Lock()
        self._restarts = 0
        self._failed = False          # helper can't be kept running: draw in this process instead
        self._queue: queue.Queue = queue.Queue(maxsize=400)
        self._proc = self._spawn()
        if self._proc is None:
            self._fall_back()
            return
        self._writer = threading.Thread(target=self._write_loop, name="overlay-pipe", daemon=True)
        self._writer.start()

    @property
    def out_of_process(self) -> bool:
        return self._local is None

    @staticmethod
    def _spawn():
        env = dict(os.environ, **{ROLE_ENV: "overlay"})
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            return subprocess.Popen(helper_command(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, env=env, cwd=root)
        except OSError:
            return None

    def _state_messages(self) -> list[dict]:
        """What a freshly started helper needs to show exactly what the old one showed."""
        with self._lock:
            msgs = [self._last[k] for k in ("board", "suggest", "outline") if k in self._last]
            msgs.append({"op": "opacity", "value": self._opacity})
            msgs.append({"op": "show" if self._visible else "hide"})
        return msgs

    def _restart(self) -> bool:
        """Called from the writer thread when the pipe broke. True if a new helper is running."""
        if self._restarts >= self.MAX_RESTARTS:
            return False
        self._restarts += 1
        try:
            if self._proc is not None:
                self._proc.kill()
        except OSError:
            pass
        proc = self._spawn()
        if proc is None:
            return False
        self._proc = proc
        try:
            for msg in self._state_messages():
                proc.stdin.write((json.dumps(msg) + "\n").encode())
            proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            return False
        return True

    def _write_loop(self) -> None:
        while True:
            msg = self._queue.get()
            if msg is None:
                return
            data = (json.dumps(msg) + "\n").encode()
            while True:
                try:
                    self._proc.stdin.write(data)
                    self._proc.stdin.flush()
                    break
                except (BrokenPipeError, OSError, ValueError, AttributeError):
                    if not self._restart():
                        self._failed = True
                        return
                    if msg["op"] in ("board", "suggest", "clear", "outline", "opacity", "show", "hide"):
                        break  # the restart already replayed the current state, which includes msg

    def _fall_back(self) -> None:
        from .overlay import ArrowOverlay
        self._local = ArrowOverlay()
        for msg in list(self._last.values()):
            apply_message(self._local, msg)
        self._local.setWindowOpacity(self._opacity)
        self._local.setVisible(self._visible)

    def _send(self, msg: dict) -> None:
        with self._lock:
            if msg["op"] in ("board", "suggest", "clear", "outline"):
                self._last["suggest" if msg["op"] == "clear" else msg["op"]] = msg
        if self._local is None and self._failed:
            self._fall_back()
        if self._local is not None:
            apply_message(self._local, msg)
            return
        try:
            self._queue.put_nowait(msg)
        except queue.Full:
            # The helper stopped reading (the writer is stuck on a full pipe): end it. The writer's
            # write then fails, and it starts a new helper with the current state.
            self._drain()
            try:
                self._proc.kill()
            except OSError:
                pass

    def _drain(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

    # ---- ArrowOverlay interface
    def set_board(self, rect: QRect, white_bottom: bool) -> None:
        self._send({"op": "board", "rect": [rect.x(), rect.y(), rect.width(), rect.height()],
                    "white_bottom": white_bottom})

    def set_suggestions(self, arrows, badge: str = "", eval_cp=None, eval_text: str = "", show_eval: bool = False) -> None:
        self._send({"op": "suggest", "badge": badge, "eval_cp": eval_cp, "eval_text": eval_text,
                    "show_eval": show_eval,
                    "arrows": [{"uci": a.move.uci(), "color": a.color, "width": a.width, "alpha": a.alpha,
                                "hint": a.hint} for a in arrows]})

    def clear(self, badge: str = "") -> None:
        self._send({"op": "clear", "badge": badge})

    def flash_outline(self, on: bool) -> None:
        self._send({"op": "outline", "on": on})

    def setWindowOpacity(self, value: float) -> None:
        self._opacity = value
        self._send({"op": "opacity", "value": value})

    def show(self) -> None:
        self._visible = True
        self._send({"op": "show"})

    def hide(self) -> None:
        self._visible = False
        self._send({"op": "hide"})

    def setVisible(self, on: bool) -> None:
        self.show() if on else self.hide()

    def isVisible(self) -> bool:
        return self._visible

    def close(self) -> None:
        self._visible = False
        if self._local is None and self._proc is not None:
            self._drain()
            self._queue.put_nowait(None)
            try:
                self._writer.join(timeout=1)
            except RuntimeError:
                pass
            try:
                self._proc.stdin.write(b'{"op": "quit"}\n')
                self._proc.stdin.flush()
                self._proc.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass
        if self._local is not None:
            self._local.close()


if __name__ == "__main__":
    host_main()
