"""macOS integration: list and capture individual windows, Screen Recording permission,
global hotkeys, app icons and sounds. Everything degrades to a no-op elsewhere."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass

import numpy as np

IS_MAC = sys.platform == "darwin"

if IS_MAC:
    try:
        import AppKit
        import Quartz
    except ImportError:  # running from source without pyobjc
        Quartz = AppKit = None
else:
    Quartz = AppKit = None

AVAILABLE = Quartz is not None
PRACTICE_TITLE = "Practice Board"


@dataclass
class WindowInfo:
    id: int
    pid: int
    app: str
    title: str
    x: float
    y: float
    w: float
    h: float
    onscreen: bool = True

    @property
    def label(self) -> str:
        return f"{self.app} — {self.title}" if self.title else self.app


def _parse(d) -> WindowInfo | None:
    b = d.get("kCGWindowBounds")
    if not b:
        return None
    return WindowInfo(
        id=int(d.get("kCGWindowNumber", 0)),
        pid=int(d.get("kCGWindowOwnerPID", 0)),
        app=str(d.get("kCGWindowOwnerName") or ""),
        title=str(d.get("kCGWindowName") or ""),
        x=float(b["X"]), y=float(b["Y"]), w=float(b["Width"]), h=float(b["Height"]),
        onscreen=bool(d.get("kCGWindowIsOnscreen", False)),
    )


def _normal(d, own_pid: int) -> bool:
    return (
        d.get("kCGWindowLayer", 1) == 0
        and float(d.get("kCGWindowAlpha", 1.0)) > 0.05
        and int(d.get("kCGWindowOwnerPID", 0)) != own_pid
    )


def list_windows(min_size: int = 160, all_spaces: bool = True) -> list[WindowInfo]:
    """Ordinary app windows, front to back (ours excluded). With all_spaces, windows on other
    desktops and full-screen apps are included too (onscreen=False), after the visible ones."""
    if not AVAILABLE:
        return []
    base = Quartz.kCGWindowListOptionAll if all_spaces else Quartz.kCGWindowListOptionOnScreenOnly
    opts = base | Quartz.kCGWindowListExcludeDesktopElements
    own = os.getpid()
    out = []
    for d in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
        # Our own windows are skipped, except the built-in practice board.
        if int(d.get("kCGWindowOwnerPID", 0)) == own and d.get("kCGWindowName") != PRACTICE_TITLE:
            continue
        if not _normal(d, -1):
            continue
        info = _parse(d)
        if not info or info.w < min_size or info.h < min_size or not info.app:
            continue
        if not info.onscreen and not info.title:
            continue  # hidden helper windows apps keep around
        out.append(info)
    out.sort(key=lambda w: not w.onscreen)
    return out


def window_info(window_id: int) -> WindowInfo | None:
    """Current position/visibility of a window, or None once it's closed."""
    if not AVAILABLE:
        return None
    rows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionIncludingWindow, window_id) or []
    for d in rows:
        if int(d.get("kCGWindowNumber", 0)) == window_id:
            return _parse(d)
    return None


def find_window(app: str, title: str) -> WindowInfo | None:
    """Re-find a window by app and title, e.g. after the app was restarted."""
    candidates = [w for w in list_windows() if w.app == app]
    for w in candidates:
        if w.title == title:
            return w
    return candidates[0] if candidates else None


def covering(window_id: int, rect: tuple[float, float, float, float], owner_pid: int = 0) -> tuple[float, str]:
    """How much of `rect` (screen coords) is hidden by windows in front, and by which one.
    Untitled windows of the board's own app (e.g. the backdrop behind a full-screen window) don't count."""
    if not AVAILABLE:
        return 0.0, ""
    x, y, w, h = rect
    rows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenAboveWindow, window_id) or []
    worst, who = 0.0, ""
    for d in rows:
        if not _normal(d, -1):
            continue
        o = _parse(d)
        if o is None or (owner_pid and o.pid == owner_pid and not o.title):
            continue
        ix = max(0.0, min(x + w, o.x + o.w) - max(x, o.x))
        iy = max(0.0, min(y + h, o.y + o.h) - max(y, o.y))
        frac = ix * iy / max(w * h, 1.0)
        if frac > worst:
            worst, who = frac, f"{o.app} '{o.title}' {int(o.w)}x{int(o.h)} at ({int(o.x)},{int(o.y)})"
    return worst, who


def covered_fraction(window_id: int, rect: tuple[float, float, float, float]) -> float:
    return covering(window_id, rect)[0]


def capture_window(window_id: int, rect: tuple[float, float, float, float] | None = None) -> np.ndarray | None:
    """RGB image of just this window (other windows and our overlay are left out).
    `rect` is in screen coordinates; None captures the whole window."""
    if not AVAILABLE:
        return None
    area = Quartz.CGRectNull if rect is None else Quartz.CGRectMake(*rect)
    img = Quartz.CGWindowListCreateImage(
        area, Quartz.kCGWindowListOptionIncludingWindow, window_id, Quartz.kCGWindowImageBoundsIgnoreFraming
    )
    if img is None:
        return None
    w, h = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    if w == 0 or h == 0:
        return None
    bpr = Quartz.CGImageGetBytesPerRow(img)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
    bgra = np.frombuffer(data, np.uint8).reshape(h, bpr)[:, : w * 4].reshape(h, w, 4)
    return bgra[:, :, 2::-1].copy()


def screen_capture_allowed() -> bool:
    if not AVAILABLE:
        return True
    return bool(Quartz.CGPreflightScreenCaptureAccess())


def request_screen_capture() -> bool:
    """Shows the system prompt (once) and adds the app to the Screen Recording list."""
    if not AVAILABLE:
        return True
    return bool(Quartz.CGRequestScreenCaptureAccess())


def open_screen_recording_settings() -> None:
    if IS_MAC:
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"])


def reveal_in_finder(path: str) -> None:
    if IS_MAC:
        subprocess.Popen(["open", path])


def app_icon_png(pid: int, size: int = 64) -> bytes | None:
    if AppKit is None:
        return None
    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None or app.icon() is None:
        return None
    rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 0)
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    app.icon().drawInRect_fromRect_operation_fraction_(
        ((0, 0), (size, size)), AppKit.NSZeroRect, AppKit.NSCompositingOperationCopy, 1.0)
    AppKit.NSGraphicsContext.restoreGraphicsState()
    return bytes(rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {}))


def _native(widget) -> bool:
    """Only real Cocoa windows have an NSView behind winId() (not the offscreen platform in tests)."""
    from PySide6.QtGui import QGuiApplication
    return AppKit is not None and QGuiApplication.platformName() == "cocoa"


def float_on_all_spaces(widget) -> bool:
    """Let a Qt window appear on every desktop, including over other apps' full-screen windows."""
    if not _native(widget):
        return False
    try:
        import objc
        view = objc.objc_object(c_void_p=ctypes.c_void_p(int(widget.winId())))
        win = view.window()
        if win is None:
            return False
        win.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle)
        win.setLevel_(AppKit.NSStatusWindowLevel)
        win.setHidesOnDeactivate_(False)
        return True
    except Exception:
        return False


def hide_title_text(widget) -> bool:
    """Keep the window's title for Mission Control and the Window menu, but don't draw it: the
    sidebar runs up behind the traffic lights instead."""
    if not _native(widget):
        return False
    try:
        import objc
        view = objc.objc_object(c_void_p=ctypes.c_void_p(int(widget.winId())))
        win = view.window()
        if win is None:
            return False
        win.setTitleVisibility_(AppKit.NSWindowTitleHidden)
        win.setTitlebarAppearsTransparent_(True)
        return True
    except Exception:
        return False


def app_bundle_path() -> str | None:
    """Path of the running .app, or None when running from source."""
    if getattr(sys, "frozen", False):
        exe = os.path.realpath(sys.executable)
        marker = ".app/Contents/MacOS/"
        if marker in exe:
            return exe[: exe.index(marker) + 4]
    return None


def relaunch_after_exit() -> None:
    """Start a fresh copy of the app as soon as this process exits (used after granting permissions)."""
    bundle = app_bundle_path()
    if bundle:
        cmd = f'open "{bundle}"'
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = f'cd "{root}" && "{sys.executable}" -m metalmate'
    subprocess.Popen(["/bin/sh", "-c", f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.2; done; {cmd}"],
                     start_new_session=True)


def activate_app(pid: int) -> None:
    if AppKit is None:
        return
    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is not None:
        app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)


def play_sound(name: str = "Tink") -> None:
    if AppKit is None:
        return
    sound = AppKit.NSSound.soundNamed_(name)
    if sound is not None:
        sound.play()


# --------------------------------------------------------------- global hotkeys
# Carbon's RegisterEventHotKey works without Accessibility permission, unlike event taps.

KEY_CODES = {
    "A": 0x00, "S": 0x01, "D": 0x02, "F": 0x03, "H": 0x04, "G": 0x05, "Z": 0x06, "X": 0x07, "C": 0x08,
    "V": 0x09, "B": 0x0B, "Q": 0x0C, "W": 0x0D, "E": 0x0E, "R": 0x0F, "Y": 0x10, "T": 0x11, "1": 0x12,
    "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "9": 0x19, "7": 0x1A, "8": 0x1C, "0": 0x1D,
    "O": 0x1F, "U": 0x20, "I": 0x22, "P": 0x23, "L": 0x25, "J": 0x26, "K": 0x28, "N": 0x2D, "M": 0x2E,
}
MOD_CMD, MOD_SHIFT, MOD_OPTION, MOD_CONTROL = 1 << 8, 1 << 9, 1 << 11, 1 << 12


def _fourcc(s: str) -> int:
    return int.from_bytes(s.encode("ascii"), "big")


class _HotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class GlobalHotkeys:
    """Register system-wide shortcuts; callbacks run on the main thread."""

    def __init__(self) -> None:
        self._callbacks: dict[int, object] = {}
        self._refs: list[ctypes.c_void_p] = []
        self._carbon = None
        self._handler = None
        if not IS_MAC:
            return
        try:
            carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
            carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
            carbon.InstallEventHandler.argtypes = [
                ctypes.c_void_p, _HANDLER, ctypes.c_uint32, ctypes.POINTER(_EventTypeSpec),
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            carbon.RegisterEventHotKey.argtypes = [
                ctypes.c_uint32, ctypes.c_uint32, _HotKeyID, ctypes.c_void_p, ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p)]
            carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
            carbon.GetEventKind.argtypes = [ctypes.c_void_p]
            carbon.GetEventKind.restype = ctypes.c_uint32
            carbon.GetEventParameter.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_ulong,
                ctypes.c_void_p, ctypes.c_void_p]
            self._handler = _HANDLER(self._on_event)
            # kEventClassKeyboard: kEventHotKeyPressed (5) and kEventHotKeyReleased (6)
            specs = (_EventTypeSpec * 2)(_EventTypeSpec(_fourcc("keyb"), 5), _EventTypeSpec(_fourcc("keyb"), 6))
            ref = ctypes.c_void_p()
            status = carbon.InstallEventHandler(
                carbon.GetApplicationEventTarget(), self._handler, 2, specs, None, ctypes.byref(ref))
            if status == 0:
                self._carbon = carbon
        except (OSError, AttributeError):
            self._carbon = None

    @property
    def available(self) -> bool:
        return self._carbon is not None

    def register(self, key: str, modifiers: int, callback, on_release=None) -> bool:
        """callback runs on key-down, on_release (optional) on key-up. False if unavailable or the
        combination is already taken by another app."""
        if self._carbon is None or key not in KEY_CODES:
            return False
        self._next_id = getattr(self, "_next_id", 0) + 1
        ref = ctypes.c_void_p()
        status = self._carbon.RegisterEventHotKey(
            KEY_CODES[key], modifiers, _HotKeyID(_fourcc("CHlp"), self._next_id),
            self._carbon.GetApplicationEventTarget(), 0, ctypes.byref(ref))
        if status != 0:
            return False
        self._callbacks[self._next_id] = (callback, on_release)
        self._refs.append(ref)
        return True

    def clear(self) -> None:
        if self._carbon is not None:
            for ref in self._refs:
                self._carbon.UnregisterEventHotKey(ref)
        self._refs.clear()
        self._callbacks.clear()

    def _on_event(self, _call_ref, event, _user) -> int:
        try:
            hk = _HotKeyID()
            self._carbon.GetEventParameter(
                event, _fourcc("----"), _fourcc("hkid"), None, ctypes.sizeof(hk), None, ctypes.byref(hk))
            press, release = self._callbacks.get(hk.id, (None, None))
            handler = press if self._carbon.GetEventKind(event) == 5 else release
            if handler:
                handler()
        except Exception:
            pass
        return 0


def describe_shortcut(key: str, modifiers: int) -> str:
    parts = []
    if modifiers & MOD_CONTROL:
        parts.append("⌃")
    if modifiers & MOD_OPTION:
        parts.append("⌥")
    if modifiers & MOD_SHIFT:
        parts.append("⇧")
    if modifiers & MOD_CMD:
        parts.append("⌘")
    return "".join(parts) + key
