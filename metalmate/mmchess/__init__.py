"""MetalMate's own chess library: rules (core), UCI engines (engine), PGN (pgn), piece images (svg).

Written for MetalMate. Modules elsewhere import it as `from metalmate import mmchess as chess`."""
from .core import *  # noqa: F401,F403
from .core import (BB_A1, BB_A8, BB_CORNERS, BB_H1, BB_H8, AmbiguousMoveError, Board, IllegalMoveError,  # noqa: F401
                   InvalidMoveError, LegalMoves, Move, Outcome, Piece, Status, Termination)
from . import engine, pgn, svg  # noqa: E402,F401
