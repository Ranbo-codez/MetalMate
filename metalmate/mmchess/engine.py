"""Talking to chess engines over UCI: start one, set its options, ask it to analyse or play.

`SimpleEngine` is synchronous and owned by one thread at a time (MetalMate gives each engine its
own worker thread). A background reader thread collects the engine's output lines."""
from __future__ import annotations

import dataclasses
import queue
import subprocess
import threading
import time
from typing import Any, Optional, Union

from .core import BLACK, WHITE, Board, Color, Move

MANAGED_OPTIONS = ("uci_chess960", "uci_variant", "multipv", "ponder")


class EngineError(RuntimeError):
    """The engine did something unexpected."""


class EngineTerminatedError(EngineError):
    """The engine process exited."""


# ---------------------------------------------------------------- scores

class Score:
    """A score from one side's point of view: centipawns or mate in N."""

    def score(self, *, mate_score: Optional[int] = None) -> Optional[int]:
        raise NotImplementedError

    def mate(self) -> Optional[int]:
        raise NotImplementedError

    def is_mate(self) -> bool:
        return self.mate() is not None

    def __neg__(self) -> "Score":
        raise NotImplementedError


@dataclasses.dataclass(frozen=True)
class Cp(Score):
    cp: int

    def score(self, *, mate_score: Optional[int] = None) -> Optional[int]:
        return self.cp

    def mate(self) -> Optional[int]:
        return None

    def __neg__(self) -> "Cp":
        return Cp(-self.cp)

    def __str__(self) -> str:
        return f"{self.cp:+d}"


@dataclasses.dataclass(frozen=True)
class Mate(Score):
    moves: int  # > 0: we mate in `moves`; < 0: we are mated in -`moves`; 0: we are mated now

    def score(self, *, mate_score: Optional[int] = None) -> Optional[int]:
        if mate_score is None:
            return None
        return mate_score - self.moves if self.moves > 0 else -mate_score - self.moves

    def mate(self) -> Optional[int]:
        return self.moves

    def __neg__(self) -> "Mate":
        return Mate(-self.moves)

    def __str__(self) -> str:
        return f"#{self.moves:+d}"


@dataclasses.dataclass(frozen=True)
class PovScore:
    """A score relative to the side to move (`relative`), viewable from either side."""
    relative: Score
    turn: Color

    def pov(self, color: Color) -> Score:
        return self.relative if color == self.turn else -self.relative

    def white(self) -> Score:
        return self.pov(WHITE)

    def black(self) -> Score:
        return self.pov(BLACK)

    def is_mate(self) -> bool:
        return self.relative.is_mate()

    def __str__(self) -> str:
        return str(self.relative)


# ---------------------------------------------------------------- limits, options, results

@dataclasses.dataclass
class Limit:
    time: Optional[float] = None
    depth: Optional[int] = None
    nodes: Optional[int] = None
    mate: Optional[int] = None
    white_clock: Optional[float] = None
    black_clock: Optional[float] = None
    white_inc: Optional[float] = None
    black_inc: Optional[float] = None
    remaining_moves: Optional[int] = None


@dataclasses.dataclass
class Option:
    name: str
    type: str
    default: Any
    min: Optional[int]
    max: Optional[int]
    var: list[str]

    def is_managed(self) -> bool:
        return self.name.lower() in MANAGED_OPTIONS

    def parse(self, value: Any) -> Any:
        if self.type == "check":
            return value if isinstance(value, bool) else str(value).lower() == "true"
        if self.type == "spin":
            v = int(value)
            if self.min is not None and v < self.min:
                raise EngineError(f"expected {self.name} >= {self.min}, got {v}")
            if self.max is not None and v > self.max:
                raise EngineError(f"expected {self.name} <= {self.max}, got {v}")
            return v
        return value


class _Options(dict):
    """Engine options by name, ignoring case like UCI does."""

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and any(k.lower() == key.lower() for k in self.keys())

    def __getitem__(self, key: str) -> Option:
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        raise KeyError(key)

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default


@dataclasses.dataclass
class PlayResult:
    move: Optional[Move]
    ponder: Optional[Move]
    info: dict = dataclasses.field(default_factory=dict)


# ---------------------------------------------------------------- the engine

def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class SimpleEngine:
    """A UCI engine running in a subprocess."""

    def __init__(self, process: subprocess.Popen, timeout: Optional[float]) -> None:
        self._process = process
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        self._reader = threading.Thread(target=self._read, name="uci-reader", daemon=True)
        self._reader.start()
        self.id: dict[str, str] = {}
        self.options: _Options = _Options()
        self._multipv = 1
        self._closed = False
        self._send("uci")
        self._wait_for("uciok", timeout, self._parse_uci_line)

    @classmethod
    def popen_uci(cls, command: Union[str, list[str]], *, timeout: Optional[float] = 10.0, **popen_args) -> "SimpleEngine":
        args = [command] if isinstance(command, str) else list(command)
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, bufsize=1, **popen_args)
        try:
            return cls(process, timeout)
        except BaseException:
            process.kill()
            raise

    # ---- low level
    def _read(self) -> None:
        try:
            for line in self._process.stdout:
                self._lines.put(line.rstrip("\r\n"))
        except (OSError, ValueError):
            pass
        self._lines.put(None)

    def _send(self, line: str) -> None:
        try:
            self._process.stdin.write(line + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise EngineTerminatedError(f"engine process died while sending {line!r}") from exc

    def _next_line(self, deadline: Optional[float]) -> str:
        timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("engine timed out") from None
        if line is None:
            self._lines.put(None)  # keep reporting the end to later readers
            raise EngineTerminatedError(f"engine process died unexpectedly (exit code {self._process.poll()})")
        return line

    def _wait_for(self, token: str, timeout: Optional[float], handler=None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            line = self._next_line(deadline)
            if line.strip() == token:
                return
            if handler:
                handler(line)

    def _parse_uci_line(self, line: str) -> None:
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "id" and parts[1] in ("name", "author"):
            self.id[parts[1]] = line.split(None, 2)[2]
        elif parts[:1] == ["option"]:
            opt = _parse_option(line)
            if opt:
                self.options[opt.name] = opt

    def _isready(self, timeout: Optional[float] = 60.0) -> None:
        self._send("isready")
        self._wait_for("readyok", timeout)

    # ---- configuration
    def configure(self, options: dict[str, Any]) -> None:
        for name, value in options.items():
            opt = self.options.get(name)
            if opt is None:
                raise EngineError(f"engine does not support option {name}")
            if opt.is_managed():
                raise EngineError(f"cannot set {name} which is automatically managed")
            if opt.type == "button":
                if value is not None and value is not False:
                    self._send(f"setoption name {opt.name}")
                continue
            self._send(f"setoption name {opt.name} value {_format_value(opt.parse(value))}")
        self._isready()

    def _set_multipv(self, n: int) -> None:
        if "MultiPV" in self.options and n != self._multipv:
            self._send(f"setoption name {self.options['MultiPV'].name} value {n}")
            self._multipv = n

    # ---- searching
    def _go(self, board: Board, limit: Limit) -> None:
        root = board.root()
        moves = " ".join(m.uci() for m in board.move_stack)
        position = "position fen " + root.fen()
        if moves:
            position += " moves " + moves
        self._send(position)
        go = ["go"]
        if limit.white_clock is not None:
            go += ["wtime", str(max(1, int(limit.white_clock * 1000)))]
        if limit.black_clock is not None:
            go += ["btime", str(max(1, int(limit.black_clock * 1000)))]
        if limit.white_inc is not None:
            go += ["winc", str(int(limit.white_inc * 1000))]
        if limit.black_inc is not None:
            go += ["binc", str(int(limit.black_inc * 1000))]
        if limit.remaining_moves is not None:
            go += ["movestogo", str(limit.remaining_moves)]
        if limit.depth is not None:
            go += ["depth", str(max(1, int(limit.depth)))]
        if limit.nodes is not None:
            go += ["nodes", str(max(1, int(limit.nodes)))]
        if limit.mate is not None:
            go += ["mate", str(max(1, int(limit.mate)))]
        if limit.time is not None:
            go += ["movetime", str(max(1, int(round(limit.time * 1000))))]
        if len(go) == 1:
            go.append("infinite")
        self._send(" ".join(go))

    def _search(self, board: Board, limit: Limit, multipv: int) -> tuple[list[dict], Optional[str], Optional[str]]:
        self._set_multipv(multipv)
        self._go(board, limit)
        expected = limit.time if limit.time is not None else None
        deadline = None if expected is None else time.monotonic() + expected + 30.0
        lines: dict[int, dict] = {}
        while True:
            line = self._next_line(deadline)
            if line.startswith("info"):
                info = parse_info(line, board)
                if "pv" in info or "score" in info:
                    k = info.get("multipv", 1)
                    lines[k] = {**lines.get(k, {}), **info}
            elif line.startswith("bestmove"):
                parts = line.split()
                best = parts[1] if len(parts) > 1 else None
                ponder = parts[3] if len(parts) > 3 and parts[2] == "ponder" else None
                return [lines[k] for k in sorted(lines)], best, ponder

    def analyse(self, board: Board, limit: Limit, *, multipv: Optional[int] = None, **_ignored):
        """The engine's final view of the position: one info dict, or a list of them with `multipv`."""
        infos, _, _ = self._search(board, limit, max(1, multipv or 1))
        if multipv is None:
            return infos[0] if infos else {}
        return infos[:multipv]

    def play(self, board: Board, limit: Limit, **_ignored) -> PlayResult:
        infos, best, ponder = self._search(board, limit, 1)
        move = None
        if best and best not in ("(none)", "0000"):
            try:
                move = board._normalise(Move.from_uci(best))
            except ValueError as exc:
                raise EngineError(f"engine played an invalid move {best!r}") from exc
            if not board.is_legal(move):
                raise EngineError(f"engine played an illegal move {best!r} in {board.fen()}")
        ponder_move = None
        if ponder and move:
            try:
                ponder_move = Move.from_uci(ponder)
            except ValueError:
                ponder_move = None
        return PlayResult(move, ponder_move, infos[0] if infos else {})

    # ---- shutting down
    def quit(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._send("quit")
        except EngineError:
            pass
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2)

    def close(self) -> None:
        self.quit()

    def __enter__(self) -> "SimpleEngine":
        return self

    def __exit__(self, *exc) -> None:
        self.quit()

    def __del__(self) -> None:
        try:
            if not self._closed and self._process.poll() is None:
                self._process.kill()
        except Exception:
            pass


def _parse_option(line: str) -> Optional[Option]:
    """`option name Hash type spin default 16 min 1 max 33554432` (names may contain spaces)."""
    tokens = line.split()[1:]
    keys = ("name", "type", "default", "min", "max", "var")
    fields: dict[str, list[str]] = {}
    current = None
    var: list[str] = []
    for tok in tokens:
        if tok in keys and (tok != "default" or current != "default"):
            if current == "var" and fields.get("var"):
                var.append(" ".join(fields.pop("var")))
            current = tok
            fields.setdefault(tok, [])
            continue
        if current:
            fields[current].append(tok)
    if current == "var" and fields.get("var"):
        var.append(" ".join(fields.pop("var")))
    name = " ".join(fields.get("name", []))
    kind = " ".join(fields.get("type", []))
    if not name or not kind:
        return None
    default: Any = " ".join(fields["default"]) if "default" in fields else None
    lo = int(" ".join(fields["min"])) if fields.get("min") else None
    hi = int(" ".join(fields["max"])) if fields.get("max") else None
    if kind == "check" and default is not None:
        default = default.lower() == "true"
    elif kind == "spin" and default not in (None, ""):
        try:
            default = int(default)
        except ValueError:
            pass
    if default == "<empty>":
        default = ""
    return Option(name, kind, default, lo, hi, var)


_INT_FIELDS = ("depth", "seldepth", "multipv", "nodes", "nps", "tbhits", "hashfull", "currmovenumber", "cpuload")


def parse_info(line: str, board: Board) -> dict:
    """One `info ...` line as a dict: depth, seldepth, multipv, score (PovScore), pv (moves), ..."""
    tokens = line.split()[1:]
    info: dict = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _INT_FIELDS and i + 1 < len(tokens):
            try:
                info[tok] = int(tokens[i + 1])
            except ValueError:
                pass
            i += 2
        elif tok == "time" and i + 1 < len(tokens):
            try:
                info["time"] = int(tokens[i + 1]) / 1000.0
            except ValueError:
                pass
            i += 2
        elif tok == "score" and i + 2 < len(tokens):
            kind, value = tokens[i + 1], tokens[i + 2]
            try:
                score: Score = Cp(int(value)) if kind == "cp" else Mate(int(value))
                info["score"] = PovScore(score, board.turn)
            except ValueError:
                pass
            i += 3
            while i < len(tokens) and tokens[i] in ("lowerbound", "upperbound"):
                info[tokens[i]] = True
                i += 1
        elif tok == "wdl" and i + 3 < len(tokens):
            try:
                info["wdl"] = tuple(int(x) for x in tokens[i + 1:i + 4])
            except ValueError:
                pass
            i += 4
        elif tok == "pv":
            pv, b = [], board.copy(stack=False)
            for uci in tokens[i + 1:]:
                try:
                    move = b._normalise(Move.from_uci(uci))
                except ValueError:
                    break
                if not b.is_legal(move):
                    break
                pv.append(move)
                b.push(move)
            info["pv"] = pv
            break
        elif tok == "string":
            info["string"] = " ".join(tokens[i + 1:])
            break
        elif tok == "currmove" and i + 1 < len(tokens):
            try:
                info["currmove"] = Move.from_uci(tokens[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1
    return info


__all__ = ["SimpleEngine", "Limit", "PovScore", "Score", "Cp", "Mate", "Option", "PlayResult", "EngineError",
           "EngineTerminatedError", "parse_info", "MANAGED_OPTIONS"]

InfoDict = dict
