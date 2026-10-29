"""Render docs/social-preview.png, the picture GitHub shows when the repository link is shared.

    .venv/bin/python scripts/make_social_preview.py

Upload it in the repository's Settings → General → Social preview (GitHub has no API for it).
Run scripts/make_screenshots.py first: it uses the Live screenshot."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from metalmate.ui.logo import app_pixmap  # noqa: E402

W, H = 1280, 640
GREEN = QColor("#4ade9b")


def font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont("Helvetica Neue")
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def main() -> None:
    QApplication(sys.argv[:1])
    img = QImage(W, H, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    bg = QLinearGradient(0, 0, W, H)
    bg.setColorAt(0, QColor("#0b0d10"))
    bg.setColorAt(1, QColor("#14181d"))
    p.fillRect(0, 0, W, H, bg)
    glow = QLinearGradient(700, 0, W, 0)
    glow.setColorAt(0, QColor(74, 222, 155, 0))
    glow.setColorAt(1, QColor(74, 222, 155, 28))
    p.fillRect(700, 0, W - 700, H, glow)

    # The Live page, cropped to the board and the best-move card, on the right.
    live = QImage(str(ROOT / "docs" / "screenshots" / "live.png"))
    crop = live.copy(312, 96, 1098, 710)
    box = QRectF(640, 70, 600, 600 * crop.height() / crop.width())
    clip = QPainterPath()
    clip.addRoundedRect(box, 18, 18)
    p.save()
    p.setClipPath(clip)
    p.drawImage(box, crop)
    p.restore()
    p.setPen(QPen(QColor(255, 255, 255, 40), 1.5))
    p.drawRoundedRect(box, 18, 18)

    x = 72
    p.drawPixmap(x, 92, app_pixmap(96))
    p.setPen(QColor("#f4f6f8"))
    p.setFont(font(76, QFont.Weight.Bold))
    p.drawText(QRectF(x, 200, 560, 96), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "MetalMate")
    p.setPen(GREEN)
    p.setFont(font(34, QFont.Weight.DemiBold))
    p.drawText(QRectF(x, 300, 560, 48), Qt.AlignmentFlag.AlignLeft, "See the board. Find the move.")
    p.setPen(QColor("#aab2bc"))
    p.setFont(font(23))
    p.drawText(QRectF(x, 362, 540, 100), Qt.TextFlag.TextWordWrap,
               "A screen-reading chess companion for the Mac: it follows the game on your screen and shows "
               "the engine's best move right on your board.")

    # Small pills.
    px = x
    p.setFont(font(19, QFont.Weight.DemiBold))
    for text in ("Free", "Apple Silicon", "macOS 12+"):
        w = p.fontMetrics().horizontalAdvance(text) + 32
        r = QRectF(px, 486, w, 38)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(74, 222, 155, 30))
        p.drawRoundedRect(r, 19, 19)
        p.setPen(GREEN)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        px += w + 12

    p.setPen(QColor("#7d8692"))
    p.setFont(font(20))
    p.drawText(QRectF(x, 560, 560, 30), Qt.AlignmentFlag.AlignLeft, "by Ranbir Dhall  ·  github.com/Ranbo-codez/MetalMate")
    p.end()
    out = ROOT / "docs" / "social-preview.png"
    img.save(str(out))
    print(f"Saved {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
