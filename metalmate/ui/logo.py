"""The MetalMate mark: a faceted, brushed-metal knight with one mint facet (the "best move"),
plus the app icon and wordmark. Drawn in code so it's crisp at every size."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

# Knight facing left, on a 100x100 grid. Each facet is (points, shade); shades go from deep
# graphite (0) to bright steel (1) so the piece reads as a lit metal object.
FACETS = [
    # muzzle and jaw
    ([(13, 46), (19, 36), (31, 38), (24, 46)], 0.95),
    ([(13, 46), (24, 46), (31, 51), (19, 52)], 0.5),
    # forehead (accent) and cheek
    ([(19, 36), (30, 25), (38, 31), (31, 38)], 1.0),
    ([(31, 38), (38, 31), (46, 40), (42, 52), (31, 51), (24, 46)], 0.82),
    # ear and crown
    ([(36, 19), (41, 6), (47, 17), (40, 24)], 0.9),
    ([(30, 25), (36, 19), (40, 24), (47, 17), (52, 28), (38, 31)], 0.72),
    # mane
    ([(47, 17), (59, 16), (64, 30), (52, 28)], 0.42),
    ([(59, 16), (70, 30), (72, 44), (64, 30)], 0.22),
    # neck
    ([(38, 31), (52, 28), (64, 30), (58, 46), (46, 40)], 0.62),
    ([(64, 30), (72, 44), (74, 56), (58, 46)], 0.3),
    ([(46, 40), (58, 46), (56, 60), (42, 52)], 0.7),
    # chest and body
    ([(42, 52), (56, 60), (52, 78), (30, 78), (35, 62)], 0.9),
    ([(58, 46), (74, 56), (73, 78), (52, 78), (56, 60)], 0.36),
    # collar and base
    ([(26, 78), (76, 78), (80, 84), (20, 84)], 0.66),
    ([(20, 84), (80, 84), (80, 91), (20, 91)], 0.28),
]
ACCENT_FACET = 2  # the forehead catches the light in mint
EYE = (30, 33)

MINT = QColor("#4ade9b")
MINT_LIGHT = QColor("#9df5c9")


def _steel(shade: float) -> QColor:
    """Graphite → cool steel → near-white, slightly blue in the mid-tones like brushed metal."""
    stops = [(0.0, (34, 38, 46)), (0.55, (150, 160, 174)), (1.0, (246, 248, 251))]
    shade = max(0.0, min(1.0, shade))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if shade <= t1:
            f = (shade - t0) / (t1 - t0)
            return QColor(*(int(a + (b - a) * f) for a, b in zip(c0, c1)))
    return QColor(*stops[-1][1])


def paint_knight(p: QPainter, rect: QRectF, accent: bool = True, reveal: float = 1.0, shine: float = -1.0,
                 mono: QColor | None = None) -> None:
    """Draw the knight into `rect`. reveal 0..1 fades facets in one by one (startup animation);
    shine 0..1 sweeps a highlight across; mono draws a flat single-colour version."""
    s = min(rect.width(), rect.height()) / 100
    ox = rect.x() + (rect.width() - 100 * s) / 2
    oy = rect.y() + (rect.height() - 100 * s) / 2
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    n = len(FACETS)
    outline = QPainterPath()
    for i, (pts, shade) in enumerate(FACETS):
        t = max(0.0, min(1.0, reveal * (n + 3) - i))  # stagger
        if t <= 0:
            continue
        poly = QPolygonF([QPointF(ox + x * s, oy + y * s) for x, y in pts])
        path = QPainterPath()
        path.addPolygon(poly)
        path.closeSubpath()
        outline = outline.united(path)
        if mono is not None:
            color = QColor(mono)
        elif accent and i == ACCENT_FACET:
            grad = QLinearGradient(poly.boundingRect().topLeft(), poly.boundingRect().bottomRight())
            grad.setColorAt(0, MINT_LIGHT)
            grad.setColorAt(1, MINT)
            p.setOpacity(t)
            p.fillPath(path, grad)
            p.setOpacity(1)
            continue
        else:
            # brushed metal: each facet a touch lighter at the top
            box = poly.boundingRect()
            grad = QLinearGradient(box.topLeft(), box.bottomLeft())
            top, bottom = _steel(shade + 0.07), _steel(shade - 0.07)
            top.setAlphaF(t)
            bottom.setAlphaF(t)
            grad.setColorAt(0, top)
            grad.setColorAt(1, bottom)
            p.fillPath(path, grad)
            continue
        color.setAlphaF(color.alphaF() * t)
        p.fillPath(path, color)
    if mono is None and reveal >= 1:
        # hairline edges so facets read as cut metal
        p.setPen(QPen(QColor(8, 10, 13, 70 if s > 0.5 else 35), max(0.5, 0.45 * s)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for pts, _ in FACETS:
            p.drawPolygon(QPolygonF([QPointF(ox + x * s, oy + y * s) for x, y in pts]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0b0c0f"))
        p.drawEllipse(QPointF(ox + EYE[0] * s, oy + EYE[1] * s), 1.9 * s, 1.9 * s)
    if 0 <= shine <= 1 and not outline.isEmpty():
        p.setClipPath(outline)
        x = ox + (-30 + 160 * shine) * s
        grad = QLinearGradient(QPointF(x - 18 * s, oy), QPointF(x + 18 * s, oy + 20 * s))
        grad.setColorAt(0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.5, QColor(255, 255, 255, 150))
        grad.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(ox, oy, 100 * s, 100 * s), grad)
    p.restore()


def paint_app_icon(p: QPainter, size: float) -> None:
    """macOS-style squircle: deep graphite with a soft top light, the knight centred."""
    inset = size * 0.085
    body = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    path = QPainterPath()
    path.addRoundedRect(body, body.width() * 0.225, body.width() * 0.225)
    grad = QLinearGradient(body.topLeft(), body.bottomLeft())
    grad.setColorAt(0, QColor("#22262e"))
    grad.setColorAt(1, QColor("#0c0d10"))
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillPath(path, grad)
    p.save()
    p.setClipPath(path)
    glow = QLinearGradient(body.topLeft(), QPointF(body.x(), body.y() + body.height() * 0.5))
    glow.setColorAt(0, QColor(255, 255, 255, 26))
    glow.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillRect(body, glow)
    p.restore()
    p.setPen(QPen(QColor(255, 255, 255, 22), max(1.0, size / 256)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    # a soft mint glow behind the piece
    p.save()
    p.setClipPath(path)
    from PySide6.QtGui import QRadialGradient
    glow = QRadialGradient(QPointF(body.center().x(), body.y() + body.height() * 0.62), body.width() * 0.5)
    glow.setColorAt(0, QColor(74, 222, 155, 46))
    glow.setColorAt(1, QColor(74, 222, 155, 0))
    p.fillRect(body, glow)
    p.restore()
    k = body.width() * 0.78
    paint_knight(p, QRectF(body.center().x() - k / 2, body.center().y() - k / 2 + body.height() * 0.01, k, k))


def app_pixmap(size: int = 512) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    paint_app_icon(p, size)
    p.end()
    return pix


def mark_pixmap(size: int, ratio: float = 2.0) -> QPixmap:
    pix = QPixmap(int(size * ratio), int(size * ratio))
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    paint_knight(p, QRectF(0, 0, size * ratio, size * ratio))
    p.end()
    pix.setDevicePixelRatio(ratio)
    return pix


def app_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 32, 64, 128, 256, 512):
        icon.addPixmap(app_pixmap(s))
    return icon


def tray_icon() -> QIcon:
    """Single-colour knight as a template image, so macOS tints it for light/dark menu bars."""
    pix = QPixmap(44, 44)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    paint_knight(p, QRectF(0, 0, 44, 44), mono=QColor("black"))
    p.end()
    pix.setDevicePixelRatio(2.0)
    icon = QIcon(pix)
    icon.setIsMask(True)
    return icon


def wordmark_font(px: int, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    f = QFont()
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 102)
    return f


def paint_wordmark(p: QPainter, rect: QRectF, px: int, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   opacity: float = 1.0) -> None:
    """“MetalMate”: Metal in steel, Mate in white."""
    p.save()
    p.setOpacity(opacity)
    p.setFont(wordmark_font(px))
    fm = p.fontMetrics()
    w1, w2 = fm.horizontalAdvance("Metal"), fm.horizontalAdvance("Mate")
    if align & Qt.AlignmentFlag.AlignHCenter:
        x = rect.center().x() - (w1 + w2) / 2
    else:
        x = rect.x()
    y = rect.center().y() + (fm.ascent() - fm.descent()) / 2
    grad = QLinearGradient(QPointF(x, y - fm.ascent()), QPointF(x, y))
    grad.setColorAt(0, QColor("#f3f5f8"))
    grad.setColorAt(1, QColor("#8d96a3"))
    p.setPen(QPen(grad, 1))
    p.drawText(QPointF(x, y), "Metal")
    p.setPen(QColor("#ffffff"))
    p.drawText(QPointF(x + w1, y), "Mate")
    p.restore()
