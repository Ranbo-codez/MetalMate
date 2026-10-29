"""Board vision: line the 8x8 grid up with a screenshot and recognise the pieces.

Recognition is template based. You calibrate once with the board in the starting
position, which gives a labelled sample of every piece type in whatever piece set
and board theme you use. Each square is reduced to a background-independent
descriptor (the piece's filled silhouette plus its brightness inside it), so a
piece sampled on a light square still matches the same piece on a dark or
highlighted square, and a profile keeps working if the board is resized.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from metalmate import mmchess as chess
import numpy as np
from PIL import Image

CELL = 48            # every square is resampled to CELL x CELL pixels
POOL = 2             # descriptors are average-pooled by this factor (tolerates small misalignment)
CORNER = 0.18        # corner zones are ignored: coordinate labels live there
FRAME = 3            # outer frame (px) ignored: bleed from neighbouring squares if the crop is off
RING = (1, 6)        # band (px from the edge) used to estimate the square's background colour
BG_TOL = 30.0        # RGB distance below which a pixel counts as background
LUM_WEIGHT = 1.5     # brightness vs. silhouette weight in the descriptor
PROFILE_VERSION = 1

START_PLACEMENT = chess.STARTING_BOARD_FEN


class CalibrationError(Exception):
    pass


def _make_masks() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    c = int(round(CELL * CORNER))
    corners = np.zeros((CELL, CELL), bool)
    corners[:c, :c] = corners[:c, -c:] = corners[-c:, :c] = corners[-c:, -c:] = True

    weight = np.ones((CELL, CELL), np.float32)
    weight[:FRAME, :] = weight[-FRAME:, :] = weight[:, :FRAME] = weight[:, -FRAME:] = 0
    weight[corners] = 0

    a, b = RING
    ring = np.zeros((CELL, CELL), bool)
    ring[a:CELL - a, a:CELL - a] = True
    ring[b:CELL - b, b:CELL - b] = False
    ring &= ~corners

    edge = np.ones((CELL, CELL), bool)
    edge[FRAME:CELL - FRAME, FRAME:CELL - FRAME] = False
    return weight, ring, edge


WEIGHT, RING_MASK, EDGE_MASK = _make_masks()
_LUMA = np.array([0.299, 0.587, 0.114], np.float32)


def image_to_square(row: int, col: int, white_bottom: bool) -> chess.Square:
    """Map a screen cell (row 0 = top) to a chess square."""
    if white_bottom:
        return chess.square(col, 7 - row)
    return chess.square(7 - col, row)


def square_to_image(square: chess.Square, white_bottom: bool) -> tuple[int, int]:
    """Inverse of image_to_square: (row, col) on screen."""
    f, r = chess.square_file(square), chess.square_rank(square)
    if white_bottom:
        return 7 - r, f
    return r, 7 - f


def split_squares(img: np.ndarray) -> np.ndarray:
    """(H, W, 3) board crop -> (64, CELL, CELL, 3) float32, row-major from the top-left."""
    pil = Image.fromarray(img)
    size = 8 * CELL
    shrinking = pil.width >= size and pil.height >= size
    pil = pil.resize((size, size), Image.BOX if shrinking else Image.BILINEAR)
    a = np.asarray(pil, np.float32)[:, :, :3]
    return a.reshape(8, CELL, 8, CELL, 3).transpose(0, 2, 1, 3, 4).reshape(64, CELL, CELL, 3)


_PARITY = ((np.arange(64) // 8 + np.arange(64) % 8) % 2).astype(bool)  # light/dark pattern, row-major


def _ring_mode(ring: np.ndarray) -> np.ndarray:
    """Most common colour in each square's edge ring (works for highlighted squares)."""
    out = np.empty((ring.shape[0], 3), np.float32)
    for i, px in enumerate(ring):
        q = (px // 16).astype(np.int32)
        keys = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
        top = np.bincount(keys).argmax()
        out[i] = px[keys == top].mean(axis=0)
    return out


def _backgrounds(squares: np.ndarray) -> np.ndarray:
    """Each square's background colour. Big pieces (chess.com's, say) reach into the edge ring, so a
    per-square median can land on the piece. Instead, read the board's two square colours from all
    squares of each parity and use them wherever enough of the ring still shows that colour; only
    squares that don't (highlights) fall back to their own most common edge colour."""
    ring = squares[:, RING_MASK]                                      # (64, R, 3)
    ring_med = np.median(ring, axis=1)
    bg = np.empty((64, 3), np.float32)
    for parity in (False, True):
        idx = np.flatnonzero(_PARITY == parity)
        board_colour = np.median(ring_med[idx], axis=0)
        showing = (np.linalg.norm(ring[idx] - board_colour, axis=-1) < BG_TOL).mean(axis=1)
        own = _ring_mode(ring[idx])
        bg[idx] = np.where((showing >= 0.2)[:, None], board_colour, own)
    return bg


def _silhouettes(squares: np.ndarray) -> np.ndarray:
    """Boolean piece masks: everything not flood-reachable from the square's edge through
    background-coloured pixels. Filling from the edge (rather than thresholding) keeps the
    inside of a white piece on a light square, as long as the piece has an outline."""
    bg = _backgrounds(squares)                                        # (64, 3)
    diff = np.linalg.norm(squares - bg[:, None, None, :], axis=-1)    # (64, C, C)
    # Textured boards need a looser match; measure the texture only on pixels near the background,
    # so piece pixels in the ring can't inflate it (which used to swallow whole pieces).
    ring_d = diff[:, RING_MASK]
    near = np.where(ring_d < 45, ring_d, np.nan)
    with np.errstate(all="ignore"):
        spread = np.nan_to_num(np.nanmedian(near, axis=1))
    tol = np.clip(spread * 3, BG_TOL, 45.0)
    similar = diff < tol[:, None, None]

    reach = similar & EDGE_MASK
    for _ in range(CELL * 3):
        grown = reach.copy()
        grown[:, 1:, :] |= reach[:, :-1, :]
        grown[:, :-1, :] |= reach[:, 1:, :]
        grown[:, :, 1:] |= reach[:, :, :-1]
        grown[:, :, :-1] |= reach[:, :, 1:]
        grown &= similar
        if np.array_equal(grown, reach):
            break
        reach = grown
    return ~reach


def _pool(a: np.ndarray) -> np.ndarray:
    n = CELL // POOL
    return a.reshape(a.shape[0], n, POOL, n, POOL).mean(axis=(2, 4))


@dataclass
class Features:
    desc: np.ndarray      # (64, D) descriptors
    fill: np.ndarray      # (64,) fraction of the usable square area covered by a piece
    lum: np.ndarray       # (64,) mean brightness inside the piece (0..1)


def extract(img: np.ndarray) -> Features:
    squares = split_squares(img)
    mask = _silhouettes(squares).astype(np.float32) * WEIGHT
    lum = (squares @ _LUMA) / 255.0
    area = mask.sum(axis=(1, 2))
    desc = np.concatenate(
        [_pool(mask).reshape(64, -1), LUM_WEIGHT * _pool(lum * mask).reshape(64, -1)], axis=1
    )
    return Features(
        desc=desc.astype(np.float32),
        fill=area / WEIGHT.sum(),
        lum=(lum * mask).sum(axis=(1, 2)) / np.maximum(area, 1.0),
    )


@dataclass
class BoardProfile:
    templates: np.ndarray   # (K, D)
    labels: list[str]       # piece symbol for each template, e.g. "P", "n"
    empty_fill: float       # fill fraction separating empty squares from occupied ones

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            templates=self.templates,
            labels=np.array(self.labels),
            empty_fill=self.empty_fill,
            cell=CELL,
            version=PROFILE_VERSION,
        )

    @classmethod
    def load(cls, path: Path) -> "BoardProfile | None":
        try:
            d = np.load(path)
            if int(d["version"]) != PROFILE_VERSION or int(d["cell"]) != CELL:
                return None
            return cls(d["templates"], [str(s) for s in d["labels"]], float(d["empty_fill"]))
        except (OSError, KeyError, ValueError):
            return None


@dataclass
class Recognition:
    grid: list[list[str]]   # 8x8 piece symbols as seen on screen ('.' = empty), row 0 = top
    fill: np.ndarray        # (8, 8)
    margin: np.ndarray      # (8, 8) runner-up distance / best distance; near 1 = unsure

    def placement(self, white_bottom: bool) -> str:
        """Board FEN (piece placement only) for the given orientation."""
        board = chess.Board(None)
        for r in range(8):
            for c in range(8):
                sym = self.grid[r][c]
                if sym != ".":
                    board.set_piece_at(image_to_square(r, c, white_bottom), chess.Piece.from_symbol(sym))
        return board.board_fen()

    def start_orientation(self) -> bool | None:
        """If the screen shows the initial position, whether White is at the bottom."""
        for white_bottom in (True, False):
            if self.placement(white_bottom) == START_PLACEMENT:
                return white_bottom
        return None

    def text(self) -> str:
        return "\n".join(" ".join(row) for row in self.grid)


def calibrate(img: np.ndarray) -> tuple[BoardProfile, bool]:
    """Build a profile from a screenshot of the board in the starting position.
    Returns the profile and whether White is at the bottom of the screen."""
    f = extract(img)
    fill = f.fill.reshape(8, 8)
    empty_max = float(fill[2:6].max())
    occupied_min = float(fill[[0, 1, 6, 7]].min())
    if occupied_min < 0.04 or occupied_min < empty_max * 1.5:
        raise CalibrationError(
            "That doesn't look like the starting position. Make sure the selection covers "
            "exactly the 8x8 squares and every piece is on its starting square, then try again.\n\n"
            f"(occupied-square fill {occupied_min:.3f} vs empty-square fill {empty_max:.3f})"
        )

    lum = f.lum.reshape(8, 8)
    white_bottom = bool(lum[6:8].mean() > lum[0:2].mean())

    start = chess.Board()
    rows = (0, 1, 6, 7)
    idx = [r * 8 + c for r in rows for c in range(8)]
    labels = [start.piece_at(image_to_square(r, c, white_bottom)).symbol() for r in rows for c in range(8)]
    threshold = empty_max + 0.35 * (occupied_min - empty_max)
    return BoardProfile(f.desc[idx].copy(), labels, threshold), white_bottom


def recognize(img: np.ndarray, profile: BoardProfile) -> Recognition:
    f = extract(img)
    t = profile.templates
    d2 = (f.desc ** 2).sum(1)[:, None] - 2 * f.desc @ t.T + (t ** 2).sum(1)[None, :]
    d2 = np.maximum(d2, 0)
    labels = np.array(profile.labels)
    best = d2.argmin(axis=1)
    best_d = d2[np.arange(64), best]
    rival = np.where(labels[None, :] == labels[best][:, None], np.inf, d2).min(axis=1)
    margin = rival / np.maximum(best_d, 1e-6)

    grid = []
    for r in range(8):
        row = []
        for c in range(8):
            i = r * 8 + c
            row.append("." if f.fill[i] < profile.empty_fill else str(labels[best[i]]))
        grid.append(row)
    return Recognition(grid, f.fill.reshape(8, 8), margin.reshape(8, 8))


def _fit_lines(profile: np.ndarray, start: float, step: float) -> tuple[float, float, float]:
    """Find 9 evenly spaced grid lines in an edge-strength profile near the guess.
    Returns (start, step, strength ratio vs. the profile's median)."""
    p = np.convolve(profile, [0.5, 1.0, 0.5], mode="same")
    idx = np.arange(len(p), dtype=np.float64)
    steps = np.arange(step * 0.94, step * 1.06, 0.1)[:, None, None]
    starts = np.arange(start - 0.3 * step, start + 0.3 * step, 0.5)[None, :, None]
    k = np.arange(9)[None, None, :]
    # A boundary at continuous coordinate X sits between pixels X-1 and X, i.e. diff index X-1.
    pos = starts + k * steps - 1
    vals = np.interp(pos, idx, p, left=0.0, right=0.0)
    score = vals[..., 1:8].sum(-1) + 0.5 * (vals[..., 0] + vals[..., 8])
    i, j = np.unravel_index(score.argmax(), score.shape)
    best_step, best_start = float(steps[i, 0, 0]), float(starts[0, j, 0])
    inner = vals[i, j, 1:8].mean()
    return best_start, best_step, float(inner / max(np.median(p), 1.0))


def refine_grid(img: np.ndarray, x: float, y: float, w: float, h: float) -> tuple[float, float, float, float] | None:
    """Snap a rough board rectangle (in img pixels) onto the real square boundaries.

    Horizontally adjacent squares always alternate colour, so a true vertical grid line
    shows an edge in almost every row: the per-column *median* edge strength peaks there
    and is barely affected by pieces. Same for rows. Returns None if no clear grid is found.
    """
    a = img.astype(np.float32)
    gx = np.abs(np.diff(a, axis=1)).sum(-1)
    gy = np.abs(np.diff(a, axis=0)).sum(-1)
    r0, r1 = int(max(0, y + 0.05 * h)), int(min(a.shape[0], y + 0.95 * h))
    c0, c1 = int(max(0, x + 0.05 * w)), int(min(a.shape[1], x + 0.95 * w))
    if r1 - r0 < 16 or c1 - c0 < 16:
        return None
    bx, sx, qx = _fit_lines(np.median(gx[r0:r1], axis=0), x, w / 8)
    by, sy, qy = _fit_lines(np.median(gy[:, c0:c1], axis=1), y, h / 8)
    if min(qx, qy) < 3.0 or abs(sx - sy) > 0.04 * max(sx, sy):
        return None
    return bx, by, 8 * sx, 8 * sy


def _checker_contrast(crop: np.ndarray) -> float:
    """How strongly the squares' background colours alternate like a chessboard.
    ~1 for a real board, ~0 for anything else."""
    squares = split_squares(crop)
    bg = np.median(squares[:, RING_MASK], axis=1).reshape(8, 8, 3)
    parity = (np.add.outer(np.arange(8), np.arange(8)) % 2).astype(bool)
    a, b = bg[parity], bg[~parity]
    spread = (np.median(np.linalg.norm(a - np.median(a, 0), axis=1))
              + np.median(np.linalg.norm(b - np.median(b, 0), axis=1)))
    gap = np.linalg.norm(np.median(a, 0) - np.median(b, 0))
    return float(gap / (gap + spread + 1e-6))


def find_board(img: np.ndarray, min_board_px: int = 160) -> tuple[float, float, float, float] | None:
    """Locate an 8x8 board anywhere in a screenshot. Returns (x, y, w, h) in img pixels.

    Every internal grid line of a board is an unbroken edge across the whole board (squares
    alternate colour, and pieces stay inside their squares). So for each candidate square size
    we score every position by how much of the 7 vertical and 7 horizontal internal lines are
    edges, using cumulative sums so each candidate costs a handful of lookups.
    """
    h0, w0 = img.shape[:2]
    scale = min(1.0, 560 / max(h0, w0))
    small = np.asarray(
        Image.fromarray(img).resize((max(1, round(w0 * scale)), max(1, round(h0 * scale))), Image.BOX),
        np.float32,
    )[:, :, :3]
    H, W = small.shape[:2]
    # 2-px differences so an anti-aliased boundary still registers on both of its pixels.
    ex = np.zeros((H, W), np.float32)
    ex[:, 1:-1] = np.abs(small[:, 2:] - small[:, :-2]).sum(-1) > 36
    ey = np.zeros((H, W), np.float32)
    ey[1:-1, :] = np.abs(small[2:] - small[:-2]).sum(-1) > 36
    cy = np.vstack([np.zeros((1, W), np.float32), np.cumsum(ex, axis=0)])  # cy[y, x]: edges in column x above y
    cx = np.hstack([np.zeros((H, 1), np.float32), np.cumsum(ey, axis=1)])  # cx[y, x]: edges in row y left of x

    candidates = []
    s_min = max(6.0, min_board_px * scale / 8)
    for s in np.arange(s_min, min(H, W) / 8 + 0.01, 0.25):
        L = int(round(8 * s))
        ny, nx = H - L + 1, W - L + 1
        if ny <= 0 or nx <= 0:
            continue
        total = np.zeros((ny, nx), np.float32)
        for k in range(1, 8):
            o = int(round(k * s))
            total += cy[L:L + ny, o:o + nx] - cy[0:ny, o:o + nx]   # vertical line at x0 + o
            total += cx[o:o + ny, L:L + nx] - cx[o:o + ny, 0:nx]   # horizontal line at y0 + o
        score = total / (14 * L)
        i = int(score.argmax())
        y0, x0 = divmod(i, nx)
        candidates.append((float(score.flat[i]), x0, y0, L))

    candidates.sort(reverse=True)
    for score, x0, y0, L in candidates[:6]:
        if score < 0.55:
            break
        x, y, side = x0 / scale, y0 / scale, L / scale
        refined = refine_grid(img, x, y, side, side)
        if refined is not None:
            x, y, w, h = refined
        else:
            w = h = side
        xi, yi = int(round(x)), int(round(y))
        crop = img[max(0, yi):yi + int(round(h)), max(0, xi):xi + int(round(w))]
        if crop.shape[0] >= 64 and crop.shape[1] >= 64 and _checker_contrast(crop) > 0.6:
            return x, y, w, h
    return None


# Why calibration failed, in plain words. `kind` lets the UI offer the right fix.
BLANK, NOT_A_BOARD, NOT_START = "blank", "not_a_board", "not_start"


def explain_calibration_failure(img: np.ndarray | None) -> tuple[str, str]:
    """Returns (kind, message) for a screenshot that calibrate() rejected."""
    if img is None or img.size == 0 or float(img.std()) < 6.0:
        return BLANK, ("The screenshot of that window came back blank, so macOS isn't letting MetalMate see it. "
                       "Allow MetalMate under Screen Recording in System Settings, then relaunch MetalMate "
                       "(macOS only applies that permission after a relaunch).")
    if img.shape[0] < 64 or img.shape[1] < 64 or _checker_contrast(img) < 0.5:
        return NOT_A_BOARD, ("The marked area doesn't line up with a chessboard any more. The page may have "
                             "scrolled, zoomed or resized. Use “Choose window…” to mark the board again.")
    pieces = int((extract(img).fill > 0.12).sum())
    return NOT_START, (f"I can see about {pieces} pieces, but learning a new board needs the starting position "
                       "(all 32 pieces on their home squares). Start a new game or open an analysis board in the "
                       "starting position. MetalMate will then learn the board by itself, or press Calibrate.")
