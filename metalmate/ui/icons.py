"""Line icons drawn on a 24×24 grid (1.7px strokes, round caps), tinted per use."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

from . import theme

# ops: ("l", x1, y1, x2, y2) line · ("r", x, y, w, h, radius) rect · ("c", cx, cy, r) circle
#      ("d", cx, cy, r) filled dot · ("a", cx, cy, r, start_deg, span_deg) arc
#      ("p", [(x, y), ...], closed) polyline · ("f", [(x, y), ...]) filled polygon
ICONS: dict[str, list] = {
    "live": [("d", 12, 12, 2.2), ("a", 12, 12, 6, -50, 100), ("a", 12, 12, 6, 130, 100),
             ("a", 12, 12, 10, -45, 90), ("a", 12, 12, 10, 135, 90)],
    "games": [("r", 5, 3.5, 14, 17, 2.5), ("l", 8.5, 8.5, 15.5, 8.5), ("l", 8.5, 12, 15.5, 12), ("l", 8.5, 15.5, 13, 15.5)],
    "stats": [("l", 6, 19, 6, 13), ("l", 12, 19, 12, 6), ("l", 18, 19, 18, 10), ("l", 3.5, 20.5, 20.5, 20.5)],
    "boards": [("r", 4, 4, 16, 16, 2.5), ("l", 12, 4, 12, 20), ("l", 4, 12, 20, 12),
               ("f", [(4.8, 4.8), (12, 4.8), (12, 12), (4.8, 12)]), ("f", [(12, 12), (19.2, 12), (19.2, 19.2), (12, 19.2)])],
    "engines": [("r", 7, 7, 10, 10, 2), ("r", 10, 10, 4, 4, 0.8), ("l", 10, 3.5, 10, 7), ("l", 14, 3.5, 14, 7),
                ("l", 10, 17, 10, 20.5), ("l", 14, 17, 14, 20.5), ("l", 3.5, 10, 7, 10), ("l", 3.5, 14, 7, 14),
                ("l", 17, 10, 20.5, 10), ("l", 17, 14, 20.5, 14)],
    "settings": [("l", 4, 7, 20, 7), ("l", 4, 12, 20, 12), ("l", 4, 17, 20, 17),
                 ("c", 9, 7, 2.2), ("c", 15, 12, 2.2), ("c", 8, 17, 2.2)],
    "play": [("f", [(8, 5.5), (19, 12), (8, 18.5)])],
    "stop": [("r", 6.5, 6.5, 11, 11, 2.5)],
    "flip": [("l", 8, 5, 8, 19), ("p", [(4.5, 8.5), (8, 5), (11.5, 8.5)], False),
             ("l", 16, 5, 16, 19), ("p", [(12.5, 15.5), (16, 19), (19.5, 15.5)], False)],
    "plus": [("l", 12, 5, 12, 19), ("l", 5, 12, 19, 12)],
    "minus": [("l", 5, 12, 19, 12)],
    "trash": [("l", 4.5, 7, 19.5, 7), ("p", [(6.5, 7), (7.5, 19.5), (16.5, 19.5), (17.5, 7)], False),
              ("p", [(9.5, 7), (10, 4.5), (14, 4.5), (14.5, 7)], False), ("l", 10.5, 10.5, 10.5, 16), ("l", 13.5, 10.5, 13.5, 16)],
    "star": [("p", [(12, 3.8), (14.5, 9.2), (20.2, 9.6), (15.8, 13.4), (17.2, 19.2), (12, 16), (6.8, 19.2), (8.2, 13.4),
                    (3.8, 9.6), (9.5, 9.2)], True)],
    "star_filled": [("f", [(12, 3.8), (14.5, 9.2), (20.2, 9.6), (15.8, 13.4), (17.2, 19.2), (12, 16), (6.8, 19.2),
                           (8.2, 13.4), (3.8, 9.6), (9.5, 9.2)])],
    "folder": [("p", [(3.5, 7), (3.5, 18.5), (20.5, 18.5), (20.5, 8.5), (11.5, 8.5), (9.5, 5.5), (3.5, 5.5), (3.5, 7)], True)],
    "export": [("p", [(9, 7), (5, 7), (5, 19), (19, 19), (19, 7), (15, 7)], False), ("l", 12, 3.5, 12, 14),
               ("p", [(8.5, 7), (12, 3.5), (15.5, 7)], False)],
    "download": [("l", 12, 4, 12, 15), ("p", [(7.5, 10.5), (12, 15), (16.5, 10.5)], False), ("l", 5, 19.5, 19, 19.5)],
    "search": [("c", 10.5, 10.5, 6), ("l", 15, 15, 20, 20)],
    "filter": [("p", [(4, 5), (20, 5), (14, 12.5), (14, 19), (10, 17), (10, 12.5), (4, 5)], True)],
    "eye": [("p", [(2.5, 12), (6, 7.5), (12, 5.5), (18, 7.5), (21.5, 12), (18, 16.5), (12, 18.5), (6, 16.5), (2.5, 12)], True),
            ("c", 12, 12, 3.2)],
    "eye_off": [("p", [(2.5, 12), (6, 7.5), (12, 5.5), (18, 7.5), (21.5, 12), (18, 16.5), (12, 18.5), (6, 16.5), (2.5, 12)],
                 True), ("l", 4, 20, 20, 4)],
    "bulb": [("p", [(9, 16), (8.2, 13.5), (6.2, 10.5), (6.5, 7), (9, 4.5), (12, 3.8), (15, 4.5), (17.5, 7), (17.8, 10.5),
                    (15.8, 13.5), (15, 16)], False), ("l", 9, 16, 15, 16), ("l", 9.5, 19, 14.5, 19), ("l", 10.5, 21.5, 13.5, 21.5)],
    "speaker": [("f", [(4, 9.5), (8, 9.5), (13, 5), (13, 19), (8, 14.5), (4, 14.5)]), ("a", 13, 12, 4, -45, 90),
                ("a", 13, 12, 7.5, -45, 90)],
    "speaker_off": [("f", [(4, 9.5), (8, 9.5), (13, 5), (13, 19), (8, 14.5), (4, 14.5)]), ("l", 16, 9, 21, 15),
                    ("l", 21, 9, 16, 15)],
    "refresh": [("a", 12, 12, 7.5, 40, 290), ("p", [(17.8, 3.6), (18.4, 7.8), (14.2, 8.4)], False)],
    "sync": [("a", 12, 12, 7.5, 30, 150), ("a", 12, 12, 7.5, 210, 150), ("p", [(18.5, 4.5), (18.5, 8.3), (14.7, 8.3)], False),
             ("p", [(5.5, 19.5), (5.5, 15.7), (9.3, 15.7)], False)],
    "chevron_down": [("p", [(6, 9.5), (12, 15.5), (18, 9.5)], False)],
    "chevron_left": [("p", [(14.5, 6), (8.5, 12), (14.5, 18)], False)],
    "chevron_right": [("p", [(9.5, 6), (15.5, 12), (9.5, 18)], False)],
    "first": [("p", [(16, 6), (10, 12), (16, 18)], False), ("l", 7, 6, 7, 18)],
    "last": [("p", [(8, 6), (14, 12), (8, 18)], False), ("l", 17, 6, 17, 18)],
    "check": [("p", [(5, 12.5), (10, 17.5), (19, 7)], False)],
    "close": [("l", 6.5, 6.5, 17.5, 17.5), ("l", 17.5, 6.5, 6.5, 17.5)],
    "more": [("d", 6, 12, 1.6), ("d", 12, 12, 1.6), ("d", 18, 12, 1.6)],
    "window": [("r", 3.5, 5, 17, 14, 2.5), ("l", 3.5, 9, 20.5, 9), ("d", 6.3, 7, 0.8), ("d", 8.8, 7, 0.8)],
    "crop": [("p", [(6, 3), (6, 18), (21, 18)], False), ("p", [(3, 6), (18, 6), (18, 21)], False)],
    "info": [("c", 12, 12, 8.5), ("l", 12, 11, 12, 16.5), ("d", 12, 7.8, 1.1)],
    "warning": [("p", [(12, 4), (21, 19.5), (3, 19.5), (12, 4)], True), ("l", 12, 10, 12, 14.5), ("d", 12, 17, 1.1)],
    "target": [("c", 12, 12, 7.5), ("c", 12, 12, 3), ("l", 12, 2.5, 12, 6), ("l", 12, 18, 12, 21.5), ("l", 2.5, 12, 6, 12),
               ("l", 18, 12, 21.5, 12)],
    "new_game": [("r", 4, 4, 16, 16, 3), ("l", 12, 8.5, 12, 15.5), ("l", 8.5, 12, 15.5, 12)],
    "external": [("p", [(13, 5), (19, 5), (19, 11)], False), ("l", 19, 5, 11, 13),
                 ("p", [(17, 14), (17, 19), (5, 19), (5, 7), (10, 7)], False)],
    "keyboard": [("r", 3, 6.5, 18, 11, 2.5), ("d", 7, 10, 0.9), ("d", 10.3, 10, 0.9), ("d", 13.6, 10, 0.9), ("d", 17, 10, 0.9),
                 ("l", 8, 14, 16, 14)],
    "copy": [("r", 8, 8, 12, 12, 2.5), ("p", [(16, 8), (16, 4), (4, 4), (4, 16), (8, 16)], False)],
    "edit": [("p", [(5, 19), (5.8, 15), (15.5, 5.3), (18.7, 8.5), (9, 18.2), (5, 19)], True), ("l", 13.5, 7.3, 16.7, 10.5)],
    "tag": [("p", [(4, 4), (11.5, 4), (20, 12.5), (12.5, 20), (4, 11.5), (4, 4)], True), ("d", 8.2, 8.2, 1.4)],
    "knight": [("p", [(8, 19.5), (8.5, 15), (11, 12), (8, 12.5), (5.5, 13.5), (4.5, 11.5), (9.5, 6.5), (11, 4), (12, 5.5),
                      (15.5, 6.5), (18.5, 11), (18.5, 19.5)], True), ("l", 6.5, 19.5, 19.5, 19.5)],
    "practice": [("r", 4, 4, 16, 16, 2.5), ("f", [(4.8, 4.8), (9.3, 4.8), (9.3, 9.3), (4.8, 9.3)]),
                 ("f", [(9.3, 9.3), (14.7, 9.3), (14.7, 14.7), (9.3, 14.7)]), ("f", [(14.7, 14.7), (19.2, 14.7), (19.2, 19.2), (14.7, 19.2)]),
                 ("f", [(14.7, 4.8), (19.2, 4.8), (19.2, 9.3), (14.7, 9.3)]), ("f", [(4.8, 14.7), (9.3, 14.7), (9.3, 19.2), (4.8, 19.2)])],
    "clock": [("c", 12, 12, 8.5), ("p", [(12, 7), (12, 12), (15.5, 14)], False)],
    "trophy": [("p", [(7, 4), (17, 4), (16.5, 10), (12, 14), (7.5, 10), (7, 4)], True), ("l", 12, 14, 12, 18),
               ("l", 8, 19.5, 16, 19.5), ("p", [(7, 6), (4, 6), (4.5, 9), (7.5, 10)], False),
               ("p", [(17, 6), (20, 6), (19.5, 9), (16.5, 10)], False)],
}


def _paint(p: QPainter, name: str, size: float, color: QColor, stroke: float = 1.7) -> None:
    s = size / 24
    pen = QPen(color, stroke * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    for op in ICONS.get(name, []):
        kind = op[0]
        if kind in ("d", "f"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
        else:
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "l":
            p.drawLine(QPointF(op[1] * s, op[2] * s), QPointF(op[3] * s, op[4] * s))
        elif kind == "r":
            p.drawRoundedRect(QRectF(op[1] * s, op[2] * s, op[3] * s, op[4] * s), op[5] * s, op[5] * s)
        elif kind in ("c", "d"):
            p.drawEllipse(QPointF(op[1] * s, op[2] * s), op[3] * s, op[3] * s)
        elif kind == "a":
            r = op[3] * s
            p.drawArc(QRectF(op[1] * s - r, op[2] * s - r, 2 * r, 2 * r), int(op[4] * 16), int(op[5] * 16))
        elif kind == "p":
            pts = [QPointF(x * s, y * s) for x, y in op[1]]
            if op[2]:
                p.drawPolygon(QPolygonF(pts))
            else:
                p.drawPolyline(QPolygonF(pts))
        elif kind == "f":
            p.drawPolygon(QPolygonF([QPointF(x * s, y * s) for x, y in op[1]]))


@lru_cache(maxsize=512)
def pixmap(name: str, size: int = 18, color: str = theme.TEXT_2, ratio: float = 2.0) -> QPixmap:
    pix = QPixmap(int(size * ratio), int(size * ratio))
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _paint(p, name, size * ratio, QColor(color))
    p.end()
    pix.setDevicePixelRatio(ratio)
    return pix


def icon(name: str, color: str = theme.TEXT_2, active: str | None = None, size: int = 18) -> QIcon:
    """An icon that turns `active` (default: text white / accent when checked) on hover/checked."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, size, color), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(pixmap(name, size, active or theme.TEXT), QIcon.Mode.Active, QIcon.State.Off)
    ic.addPixmap(pixmap(name, size, theme.ACCENT), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(pixmap(name, size, theme.ACCENT), QIcon.Mode.Active, QIcon.State.On)
    ic.addPixmap(pixmap(name, size, theme.TEXT_3), QIcon.Mode.Disabled, QIcon.State.Off)
    return ic
