"""Screenshot a rectangle of the screen as an RGB numpy array."""
from __future__ import annotations

import sys

import mss
import numpy as np

_MSS = getattr(mss, "MSS", None) or mss.mss


class ScreenGrabber:
    def __init__(self) -> None:
        self._sct = None

    def grab(self, x: int, y: int, w: int, h: int, scale: float = 1.0) -> np.ndarray:
        """Capture (x, y, w, h), given in Qt logical coordinates.

        On macOS mss also works in points, so no conversion is needed. Elsewhere mss
        uses physical pixels, so pass the screen's devicePixelRatio as `scale`.
        The returned image may be larger than w x h on Retina screens.
        """
        if self._sct is None:
            self._sct = _MSS()
        if sys.platform == "darwin":
            scale = 1.0
        region = {
            "left": int(round(x * scale)),
            "top": int(round(y * scale)),
            "width": max(1, int(round(w * scale))),
            "height": max(1, int(round(h * scale))),
        }
        shot = self._sct.grab(region)
        bgra = np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)
        return bgra[:, :, 2::-1].copy()

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None
