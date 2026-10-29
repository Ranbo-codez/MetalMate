"""Opening names for the game library. Matched by position, so transpositions work."""
from __future__ import annotations

from metalmate import mmchess as chess

_LINES = [
    ("King's Pawn Opening", "e4"),
    ("Queen's Pawn Opening", "d4"),
    ("English Opening", "c4"),
    ("Réti Opening", "Nf3"),
    ("Bird's Opening", "f4"),
    ("Nimzo-Larsen Attack", "b3"),
    ("Hungarian Opening", "g3"),
    ("Polish Opening", "b4"),
    ("Van 't Kruijs Opening", "e3"),
    ("Mieses Opening", "d3"),
    ("Grob Opening", "g4"),
    ("Sicilian Defense", "e4 c5"),
    ("French Defense", "e4 e6"),
    ("Caro-Kann Defense", "e4 c6"),
    ("Modern Defense", "e4 g6"),
    ("Alekhine's Defense", "e4 Nf6"),
    ("Scandinavian Defense", "e4 d5"),
    ("Scandinavian Defense: Main Line", "e4 d5 exd5 Qxd5 Nc3 Qa5"),
    ("Owen's Defense", "e4 b6"),
    ("Nimzowitsch Defense", "e4 Nc6"),
    ("Pirc Defense", "e4 d6 d4 Nf6 Nc3 g6"),
    ("Pirc Defense: Austrian Attack", "e4 d6 d4 Nf6 Nc3 g6 f4"),
    ("King's Pawn Game", "e4 e5"),
    ("King's Knight Opening", "e4 e5 Nf3"),
    ("Philidor Defense", "e4 e5 Nf3 d6"),
    ("Petrov's Defense", "e4 e5 Nf3 Nf6"),
    ("Elephant Gambit", "e4 e5 Nf3 d5"),
    ("Latvian Gambit", "e4 e5 Nf3 f5"),
    ("Damiano Defense", "e4 e5 Nf3 f6"),
    ("King's Knight Opening: Normal Variation", "e4 e5 Nf3 Nc6"),
    ("Ruy López", "e4 e5 Nf3 Nc6 Bb5"),
    ("Ruy López: Morphy Defense", "e4 e5 Nf3 Nc6 Bb5 a6"),
    ("Ruy López: Berlin Defense", "e4 e5 Nf3 Nc6 Bb5 Nf6"),
    ("Ruy López: Schliemann Defense", "e4 e5 Nf3 Nc6 Bb5 f5"),
    ("Ruy López: Exchange Variation", "e4 e5 Nf3 Nc6 Bb5 a6 Bxc6"),
    ("Ruy López: Closed", "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7"),
    ("Ruy López: Marshall Attack", "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 O-O c3 d5"),
    ("Italian Game", "e4 e5 Nf3 Nc6 Bc4"),
    ("Italian Game: Giuoco Piano", "e4 e5 Nf3 Nc6 Bc4 Bc5"),
    ("Italian Game: Giuoco Pianissimo", "e4 e5 Nf3 Nc6 Bc4 Bc5 d3"),
    ("Italian Game: Evans Gambit", "e4 e5 Nf3 Nc6 Bc4 Bc5 b4"),
    ("Italian Game: Hungarian Defense", "e4 e5 Nf3 Nc6 Bc4 Be7"),
    ("Italian Game: Two Knights Defense", "e4 e5 Nf3 Nc6 Bc4 Nf6"),
    ("Italian Game: Two Knights, Knight Attack", "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5"),
    ("Italian Game: Fried Liver Attack", "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5 exd5 Nxd5 Nxf7"),
    ("Scotch Game", "e4 e5 Nf3 Nc6 d4"),
    ("Scotch Game: Main Line", "e4 e5 Nf3 Nc6 d4 exd4 Nxd4"),
    ("Scotch Gambit", "e4 e5 Nf3 Nc6 d4 exd4 Bc4"),
    ("Three Knights Opening", "e4 e5 Nf3 Nc6 Nc3"),
    ("Four Knights Game", "e4 e5 Nf3 Nc6 Nc3 Nf6"),
    ("Ponziani Opening", "e4 e5 Nf3 Nc6 c3"),
    ("Vienna Game", "e4 e5 Nc3"),
    ("Vienna Gambit", "e4 e5 Nc3 Nf6 f4"),
    ("King's Gambit", "e4 e5 f4"),
    ("King's Gambit Accepted", "e4 e5 f4 exf4"),
    ("King's Gambit Declined", "e4 e5 f4 Bc5"),
    ("Bishop's Opening", "e4 e5 Bc4"),
    ("Center Game", "e4 e5 d4 exd4 Qxd4"),
    ("Danish Gambit", "e4 e5 d4 exd4 c3"),
    ("Wayward Queen Attack", "e4 e5 Qh5"),
    ("Sicilian Defense: Open", "e4 c5 Nf3 d6 d4 cxd4 Nxd4"),
    ("Sicilian Defense: Najdorf Variation", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6"),
    ("Sicilian Defense: Dragon Variation", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6"),
    ("Sicilian Defense: Classical Variation", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 Nc6"),
    ("Sicilian Defense: Scheveningen Variation", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 e6"),
    ("Sicilian Defense: Sveshnikov Variation", "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5"),
    ("Sicilian Defense: Accelerated Dragon", "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 g6"),
    ("Sicilian Defense: Taimanov Variation", "e4 c5 Nf3 e6 d4 cxd4 Nxd4 Nc6"),
    ("Sicilian Defense: Kan Variation", "e4 c5 Nf3 e6 d4 cxd4 Nxd4 a6"),
    ("Sicilian Defense: Alapin Variation", "e4 c5 c3"),
    ("Sicilian Defense: Closed", "e4 c5 Nc3"),
    ("Sicilian Defense: Grand Prix Attack", "e4 c5 Nc3 Nc6 f4"),
    ("Sicilian Defense: Smith-Morra Gambit", "e4 c5 d4 cxd4 c3"),
    ("Sicilian Defense: Rossolimo Variation", "e4 c5 Nf3 Nc6 Bb5"),
    ("Sicilian Defense: Moscow Variation", "e4 c5 Nf3 d6 Bb5+"),
    ("French Defense: Advance Variation", "e4 e6 d4 d5 e5"),
    ("French Defense: Exchange Variation", "e4 e6 d4 d5 exd5"),
    ("French Defense: Tarrasch Variation", "e4 e6 d4 d5 Nd2"),
    ("French Defense: Winawer Variation", "e4 e6 d4 d5 Nc3 Bb4"),
    ("French Defense: Classical Variation", "e4 e6 d4 d5 Nc3 Nf6"),
    ("French Defense: Rubinstein Variation", "e4 e6 d4 d5 Nc3 dxe4"),
    ("Caro-Kann Defense: Advance Variation", "e4 c6 d4 d5 e5"),
    ("Caro-Kann Defense: Exchange Variation", "e4 c6 d4 d5 exd5 cxd5"),
    ("Caro-Kann Defense: Panov Attack", "e4 c6 d4 d5 exd5 cxd5 c4"),
    ("Caro-Kann Defense: Classical Variation", "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5"),
    ("Caro-Kann Defense: Two Knights Attack", "e4 c6 Nc3 d5 Nf3"),
    ("Alekhine's Defense: Four Pawns Attack", "e4 Nf6 e5 Nd5 d4 d6 c4 Nb6 f4"),
    ("Queen's Pawn Game", "d4 d5"),
    ("Queen's Gambit", "d4 d5 c4"),
    ("Queen's Gambit Accepted", "d4 d5 c4 dxc4"),
    ("Queen's Gambit Declined", "d4 d5 c4 e6"),
    ("Queen's Gambit Declined: Exchange Variation", "d4 d5 c4 e6 Nc3 Nf6 cxd5"),
    ("Tarrasch Defense", "d4 d5 c4 e6 Nc3 c5"),
    ("Slav Defense", "d4 d5 c4 c6"),
    ("Semi-Slav Defense", "d4 d5 c4 c6 Nf3 Nf6 Nc3 e6"),
    ("Albin Countergambit", "d4 d5 c4 e5"),
    ("Chigorin Defense", "d4 d5 c4 Nc6"),
    ("London System", "d4 d5 Bf4"),
    ("London System", "d4 Nf6 Bf4"),
    ("London System", "d4 d5 Nf3 Nf6 Bf4"),
    ("Jobava London System", "d4 d5 Nc3 Nf6 Bf4"),
    ("Colle System", "d4 d5 Nf3 Nf6 e3"),
    ("Blackmar-Diemer Gambit", "d4 d5 e4"),
    ("Indian Defense", "d4 Nf6"),
    ("Trompowsky Attack", "d4 Nf6 Bg5"),
    ("King's Indian Defense", "d4 Nf6 c4 g6"),
    ("King's Indian Defense: Classical Variation", "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O Be2 e5"),
    ("King's Indian Defense: Sämisch Variation", "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 f3"),
    ("Grünfeld Defense", "d4 Nf6 c4 g6 Nc3 d5"),
    ("Nimzo-Indian Defense", "d4 Nf6 c4 e6 Nc3 Bb4"),
    ("Queen's Indian Defense", "d4 Nf6 c4 e6 Nf3 b6"),
    ("Bogo-Indian Defense", "d4 Nf6 c4 e6 Nf3 Bb4+"),
    ("Catalan Opening", "d4 Nf6 c4 e6 g3"),
    ("Benoni Defense", "d4 Nf6 c4 c5"),
    ("Modern Benoni", "d4 Nf6 c4 c5 d5 e6"),
    ("Benko Gambit", "d4 Nf6 c4 c5 d5 b5"),
    ("Budapest Gambit", "d4 Nf6 c4 e5"),
    ("Old Indian Defense", "d4 Nf6 c4 d6"),
    ("Dutch Defense", "d4 f5"),
    ("Dutch Defense: Leningrad Variation", "d4 f5 g3 Nf6 Bg2 g6"),
    ("Dutch Defense: Stonewall Variation", "d4 f5 c4 Nf6 g3 e6 Bg2 d5"),
    ("Englund Gambit", "d4 e5"),
    ("English Opening: Reversed Sicilian", "c4 e5"),
    ("English Opening: Symmetrical Variation", "c4 c5"),
    ("English Opening: Anglo-Indian Defense", "c4 Nf6"),
    ("Réti Opening: King's Indian Attack", "Nf3 d5 g3"),
    ("Bird's Opening: From's Gambit", "f4 e5"),
]


def _key(board: chess.Board) -> str:
    return board.epd()


def _build() -> dict[str, str]:
    table = {}
    for name, line in _LINES:
        b = chess.Board()
        for san in line.split():
            b.push_san(san)
        table[_key(b)] = name
    return table


TABLE = _build()


def name_for(start_fen: str, moves: list[chess.Move]) -> str:
    """Deepest named position reached in the game ('' if none, or not from the start)."""
    if start_fen.split()[0] != chess.STARTING_BOARD_FEN:
        return ""
    b = chess.Board()
    found = ""
    for move in moves[:30]:
        b.push(move)
        found = TABLE.get(_key(b), found)
    return found
