"""Draws a chess.com-style board (coordinates inside the squares, last-move highlight,
legal-move dots). Used by the offline practice board and by the tests."""
from __future__ import annotations

from metalmate import mmchess as chess
import numpy as np
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

THEMES = {
    "green": dict(light="#ebecd0", dark="#739552", hl_light="#f5f682", hl_dark="#b9ca43"),
    "brown": dict(light="#f0d9b5", dark="#b58863", hl_light="#cdd26a", hl_dark="#aaa23a"),
    "blue": dict(light="#dee3e6", dark="#8ca2ad", hl_light="#c3d887", hl_dark="#92b166"),
}


class BoardRenderer:
    def __init__(self, theme: str = "green") -> None:
        self.theme = THEMES[theme]
        self._pieces = {
            sym: QSvgRenderer(QByteArray(chess.svg.piece(chess.Piece.from_symbol(sym)).encode()))
            for sym in "PNBRQKpnbrqk"
        }

    def paint(
        self,
        p: QPainter,
        rect: QRectF,
        board: chess.Board,
        flipped: bool = False,
        lastmove: chess.Move | None = None,
        selected: chess.Square | None = None,
        targets: tuple[chess.Square, ...] = (),
        coords: bool = True,
    ) -> None:
        t = self.theme
        s = rect.width() / 8
        highlighted = {selected} if selected is not None else set()
        if lastmove:
            highlighted |= {lastmove.from_square, lastmove.to_square}
        font = QFont()
        font.setPixelSize(max(8, int(s * 0.2)))
        font.setBold(True)
        p.setFont(font)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        for row in range(8):
            for col in range(8):
                sq = chess.square(7 - col, row) if flipped else chess.square(col, 7 - row)
                light = (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1
                cell = QRectF(rect.x() + col * s, rect.y() + row * s, s, s)
                if sq in highlighted:
                    fill = t["hl_light"] if light else t["hl_dark"]
                else:
                    fill = t["light"] if light else t["dark"]
                p.fillRect(cell, QColor(fill))

                if coords:
                    p.setPen(QColor(t["dark"] if light else t["light"]))
                    pad = s * 0.05
                    if col == 0:
                        p.drawText(cell.adjusted(pad, pad * 0.6, 0, 0),
                                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                   str(chess.square_rank(sq) + 1))
                    if row == 7:
                        p.drawText(cell.adjusted(0, 0, -pad, -pad * 0.4),
                                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                                   chess.FILE_NAMES[chess.square_file(sq)])

                piece = board.piece_at(sq)
                if piece:
                    self._pieces[piece.symbol()].render(p, cell)
                if sq in targets:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(0, 0, 0, 36))
                    if piece:
                        p.setPen(QColor(0, 0, 0, 36))
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        pen = p.pen()
                        pen.setWidthF(s * 0.08)
                        p.setPen(pen)
                        p.drawEllipse(cell.adjusted(s * 0.05, s * 0.05, -s * 0.05, -s * 0.05))
                    else:
                        r = s * 0.16
                        p.drawEllipse(cell.center(), r, r)
                    p.setBrush(Qt.BrushStyle.NoBrush)

    def to_array(self, board: chess.Board, size: int, **kwargs) -> np.ndarray:
        """Render to an (size, size, 3) RGB array."""
        img = QImage(size, size, QImage.Format.Format_RGB888)
        img.fill(QColor("#302e2b"))
        p = QPainter(img)
        self.paint(p, QRectF(0, 0, size, size), board, **kwargs)
        p.end()
        return qimage_to_array(img)


def qimage_to_array(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), np.uint8, count=h * bpl).reshape(h, bpl)
    return buf[:, : w * 3].reshape(h, w, 3).copy()
