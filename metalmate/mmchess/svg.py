"""SVG images of single pieces and of whole boards."""
from __future__ import annotations

from typing import Optional

from .core import Board, Move, Piece, square_file, square_rank
from .pieces import PIECES

SQUARE_SIZE = 45
COLORS = {
    "square light": "#ffce9e",
    "square dark": "#d18b47",
    "square light lastmove": "#cdd16a",
    "square dark lastmove": "#aaa23b",
}
_HEADER = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           'version="1.2" baseProfile="tiny"')


def piece(p: Piece, size: Optional[int] = None) -> str:
    """One piece, drawn on a 45 x 45 grid."""
    dims = f' width="{size}" height="{size}"' if size else ""
    return f'{_HEADER} viewBox="0 0 {SQUARE_SIZE} {SQUARE_SIZE}"{dims}>{PIECES[p.symbol()]}</svg>'


def board(b: Optional[Board] = None, *, size: Optional[int] = None, flipped: bool = False,
          coordinates: bool = False, lastmove: Optional[Move] = None, colors: Optional[dict] = None) -> str:
    """A whole board (no coordinates or border), White at the bottom unless flipped."""
    palette = {**COLORS, **(colors or {})}
    full = 8 * SQUARE_SIZE
    dims = f' width="{size}" height="{size}"' if size else ""
    parts = [f'{_HEADER} viewBox="0 0 {full} {full}"{dims}>']
    marked = {lastmove.from_square, lastmove.to_square} if lastmove else set()
    for sq in range(64):
        f, r = square_file(sq), square_rank(sq)
        col, row = (7 - f, r) if flipped else (f, 7 - r)
        x, y = col * SQUARE_SIZE, row * SQUARE_SIZE
        shade = "light" if (f + r) % 2 else "dark"
        key = f"square {shade} lastmove" if sq in marked else f"square {shade}"
        parts.append(f'<rect x="{x}" y="{y}" width="{SQUARE_SIZE}" height="{SQUARE_SIZE}" fill="{palette[key]}"/>')
        if b is not None and (p := b.piece_at(sq)) is not None:
            parts.append(f'<g transform="translate({x}, {y})">{PIECES[p.symbol()]}</g>')
    parts.append("</svg>")
    return "".join(parts)
