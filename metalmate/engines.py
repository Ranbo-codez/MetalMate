"""Installed engines, engine profiles, and installing engines from the catalog.

An *engine* is a UCI program on disk. A *profile* is how MetalMate uses one: think time,
threads, memory, and an optional strength limit. You switch profiles (and so engines) any time,
including mid-game: the new engine is given the whole game so far."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import threading
import time
import urllib.request
import uuid
import zipfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import __version__
from . import mmchess as chess
from .catalog import CatalogEngine, Installer, machine_arch

USER_AGENT = f"MetalMate/{__version__}"


@dataclass
class EngineInfo:
    id: str
    name: str
    command: list
    source: str = "custom"          # homebrew | download | custom
    catalog_id: str = ""
    version: str = ""
    author: str = ""
    uci_name: str = ""              # what the engine calls itself, e.g. "Stockfish 19"
    added: float = 0.0

    @property
    def path(self) -> str:
        return self.command[0] if self.command else ""

    @property
    def available(self) -> bool:
        return bool(self.path) and os.path.isfile(self.path) and os.access(self.path, os.X_OK)


@dataclass
class EngineProfile:
    id: str
    name: str
    engine_id: str
    think_time: float = 0.8
    threads: int = 2
    hash_mb: int = 128
    limit_elo: int = 0              # 0 = full strength; otherwise UCI_LimitStrength + UCI_Elo
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EngineConfig:
    """Everything needed to (re)start an engine; equal configs reuse the running process."""
    command: tuple
    threads: int
    hash_mb: int
    limit_elo: int
    options: tuple
    label: str


class ProbeError(Exception):
    pass


def probe(command: list, timeout: float = 15) -> dict:
    """Start an engine, check it speaks UCI and can think, return its id and options."""
    try:
        engine = chess.engine.SimpleEngine.popen_uci(list(command), timeout=timeout)
    except FileNotFoundError:
        raise ProbeError(f"No program at {command[0]}")
    except PermissionError:
        raise ProbeError("macOS won't let that file run (it isn't executable, or it's blocked)")
    except (TimeoutError, chess.engine.EngineError, chess.engine.EngineTerminatedError, OSError) as exc:
        raise ProbeError(f"It didn't respond like a UCI chess engine ({exc.__class__.__name__})")
    try:
        engine.analyse(chess.Board(), chess.engine.Limit(time=0.05))
        return {"name": engine.id.get("name", ""), "author": engine.id.get("author", ""),
                "options": sorted(engine.options)}
    except Exception as exc:
        raise ProbeError(f"It started but couldn't analyse a position ({exc.__class__.__name__})")
    finally:
        try:
            engine.quit()
        except Exception:
            pass


class EngineRegistry:
    """engines.json: {"engines": [...], "profiles": [...]}."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._engines: dict[str, EngineInfo] = {}
        self._profiles: dict[str, EngineProfile] = {}
        self._dismissed: set[str] = set()  # built-in engines the user removed: don't add them back
        self.load()

    # ---------------------------------------------------------------- disk
    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            raw = {}
        ek = {f.name for f in fields(EngineInfo)}
        pk = {f.name for f in fields(EngineProfile)}
        self._engines = {d["id"]: EngineInfo(**{k: v for k, v in d.items() if k in ek})
                         for d in raw.get("engines", []) if "id" in d}
        self._profiles = {d["id"]: EngineProfile(**{k: v for k, v in d.items() if k in pk})
                          for d in raw.get("profiles", []) if "id" in d}
        self._dismissed = set(raw.get("dismissed", []))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"engines": [asdict(e) for e in self._engines.values()],
                                   "profiles": [asdict(p) for p in self._profiles.values()],
                                   "dismissed": sorted(self._dismissed)}, indent=2))
        tmp.replace(self.path)

    # ------------------------------------------------------------- engines
    def engines(self) -> list[EngineInfo]:
        return sorted(self._engines.values(), key=lambda e: e.added)

    def engine(self, engine_id: str | None) -> EngineInfo | None:
        return self._engines.get(engine_id or "")

    def find_by_catalog(self, catalog_id: str) -> EngineInfo | None:
        return next((e for e in self._engines.values() if e.catalog_id == catalog_id), None)

    def find_by_command(self, command: list) -> EngineInfo | None:
        """The engine started by exactly this command (same program, same arguments)."""
        key = [os.path.realpath(command[0]), *command[1:]] if command else []
        return next((e for e in self._engines.values()
                     if e.command and [os.path.realpath(e.command[0]), *e.command[1:]] == key), None)

    def add_engine(self, name: str, command: list, source: str = "custom", catalog_id: str = "",
                   version: str = "", author: str = "", uci_name: str = "", make_profile: bool = True) -> EngineInfo:
        self._dismissed.discard(catalog_id)
        existing = self.find_by_command(command)
        if existing:  # re-installed or re-added: refresh what we know about it
            existing.command, existing.uci_name = list(command), uci_name or existing.uci_name
            existing.version = version or existing.version
            self.save()
            return existing
        info = EngineInfo(uuid.uuid4().hex[:10], name, list(command), source, catalog_id, version, author,
                          uci_name, time.time())
        self._engines[info.id] = info
        if make_profile:
            self.add_profile(f"{name} · Balanced", info.id)
        self.save()
        return info

    def remove_engine(self, engine_id: str, engines_dir: Path | None = None) -> None:
        info = self._engines.pop(engine_id, None)
        if info and info.source == "bundled":
            self._dismissed.add(info.catalog_id)
        for p in [p for p in self._profiles.values() if p.engine_id == engine_id]:
            del self._profiles[p.id]
        if info and info.source == "download" and engines_dir is not None:
            folder = Path(info.path).resolve()
            root = engines_dir.resolve()
            while folder.parent != root and root in folder.parents:
                folder = folder.parent
            if folder.parent == root:
                shutil.rmtree(folder, ignore_errors=True)
        self.save()

    def rename_engine(self, engine_id: str, name: str) -> None:
        if engine_id in self._engines:
            self._engines[engine_id].name = name
            self.save()

    # ------------------------------------------------------------ profiles
    def profiles(self) -> list[EngineProfile]:
        order = {e.id: i for i, e in enumerate(self.engines())}
        return sorted(self._profiles.values(), key=lambda p: (order.get(p.engine_id, 99), p.think_time, p.name))

    def profile(self, profile_id: str | None) -> EngineProfile | None:
        return self._profiles.get(profile_id or "")

    def add_profile(self, name: str, engine_id: str, think_time: float = 0.8, threads: int = 2, hash_mb: int = 128,
                    limit_elo: int = 0, options: dict | None = None) -> EngineProfile:
        prof = EngineProfile(uuid.uuid4().hex[:10], name, engine_id, think_time, threads, hash_mb, limit_elo,
                             dict(options or {}))
        self._profiles[prof.id] = prof
        self.save()
        return prof

    def update_profile(self, prof: EngineProfile) -> None:
        self._profiles[prof.id] = prof
        self.save()

    def delete_profile(self, profile_id: str) -> None:
        self._profiles.pop(profile_id, None)
        self.save()

    def config_for(self, profile_id: str | None) -> tuple[EngineConfig | None, EngineProfile | None, EngineInfo | None]:
        prof = self.profile(profile_id)
        info = self.engine(prof.engine_id) if prof else None
        if not prof or not info:
            return None, prof, info
        cfg = EngineConfig(tuple(info.command), prof.threads, prof.hash_mb, prof.limit_elo,
                           tuple(sorted(prof.options.items())), prof.name)
        return cfg, prof, info

    # ------------------------------------------------------------- defaults
    def forget_bundled(self) -> bool:
        """Remove engines that older MetalMate builds shipped inside the app (and their profiles)."""
        gone = [e.id for e in self._engines.values() if e.source == "bundled"]
        for engine_id in gone:
            info = self._engines.pop(engine_id)
            self._dismissed.discard(info.catalog_id)
            for p in [p for p in self._profiles.values() if p.engine_id == engine_id]:
                del self._profiles[p.id]
        if gone:
            self.save()
        return bool(gone)

    def ensure_defaults(self, stockfish_path: str) -> str | None:
        """First run: register a Stockfish we can find, with three ready-made profiles.
        Returns the profile id to make active (or None if nothing changed)."""
        if not stockfish_path or self.find_by_command([stockfish_path]):
            return None
        source = "homebrew" if "/homebrew/" in stockfish_path or stockfish_path.startswith("/usr/local/") else "custom"
        info = self.add_engine("Stockfish", [stockfish_path], source, "stockfish", make_profile=False)
        self.add_profile("Stockfish · Quick", info.id, think_time=0.3, threads=2, hash_mb=64)
        balanced = self.add_profile("Stockfish · Balanced", info.id, think_time=0.8, threads=2, hash_mb=128)
        self.add_profile("Stockfish · Deep", info.id, think_time=2.5, threads=4, hash_mb=256)
        return balanced.id


# ----------------------------------------------------------------- installing

class InstallError(Exception):
    pass


def brew_path() -> str | None:
    for p in (shutil.which("brew"), "/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def _github_api(url: str, timeout: float = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class InstallJob(QObject):
    """Installs one catalog engine in a background thread."""

    progress = Signal(float, str)        # fraction 0..1 (or -1 when unknown), message
    finished = Signal(bool, str, str)    # ok, message, engine id

    def __init__(self, entry: CatalogEngine, registry: EngineRegistry, engines_dir: Path,
                 api_base: str = "https://api.github.com") -> None:
        super().__init__()
        self.entry, self.registry, self.engines_dir, self.api_base = entry, registry, engines_dir, api_base
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self.result: tuple[bool, str, str] | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"install-{self.entry.id}", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _done(self, ok: bool, message: str, engine_id: str = "") -> None:
        self.result = (ok, message, engine_id)
        self.finished.emit(ok, message, engine_id)

    def _run(self) -> None:
        errors = []
        for inst in self.entry.installers_for():
            if self._cancel.is_set():
                return self._done(False, "Cancelled.")
            try:
                command, source = (self._brew(inst) if inst.kind == "brew" else self._github(inst))
                self.progress.emit(-1, "Checking the engine works…")
                info = probe(command)
                eng = self.registry.add_engine(self.entry.name, command, source, self.entry.id,
                                               self.entry.version, self.entry.author, info["name"])
                return self._done(True, f"{info['name'] or self.entry.name} is ready.", eng.id)
            except (InstallError, ProbeError) as exc:
                errors.append(str(exc))
            except Exception as exc:  # network trouble, disk full...
                errors.append(f"{exc.__class__.__name__}: {exc}")
        if self._cancel.is_set():
            return self._done(False, "Cancelled.")
        if not errors:
            return self._done(False, f"{self.entry.name} doesn't publish a build for this Mac.")
        self._done(False, "Couldn't install: " + " · ".join(errors))

    # ---- Homebrew
    def _brew(self, inst: Installer) -> tuple[list, str]:
        brew = brew_path()
        if not brew:
            raise InstallError("Homebrew isn't installed")
        prefix = subprocess.run([brew, "--prefix"], capture_output=True, text=True, timeout=30).stdout.strip()
        binary = os.path.join(prefix or "/opt/homebrew", "bin", inst.binary)
        if not os.path.exists(binary):
            self.progress.emit(-1, f"Installing {inst.formula} with Homebrew (this can take a minute)…")
            env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1",
                       HOMEBREW_NO_ENV_HINTS="1")
            proc = subprocess.Popen([brew, "install", inst.formula], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, env=env)
            for line in proc.stdout:
                if self._cancel.is_set():
                    proc.terminate()
                    raise InstallError("Cancelled")
                line = line.strip().lstrip("=> ").strip()
                if line:
                    self.progress.emit(-1, line[:90])
            if proc.wait() != 0 or not os.path.exists(binary):
                raise InstallError(f"Homebrew couldn't install {inst.formula}")
        return [binary, *inst.args], "homebrew"

    # ---- GitHub releases
    def _github(self, inst: Installer) -> tuple[list, str]:
        pattern = inst.asset_pattern(machine_arch())
        if not pattern:
            raise InstallError("no build for this Mac")
        self.progress.emit(-1, "Finding the latest release…")
        release = _github_api(f"{self.api_base}/repos/{inst.repo}/releases/latest")
        asset = next((a for a in release.get("assets", []) if re.search(pattern, a["name"])), None)
        if asset is None:
            raise InstallError(f"the latest release has no macOS download ({release.get('tag_name', '?')})")
        tag = re.sub(r"[^\w.-]", "_", release.get("tag_name", "latest"))
        folder = self.engines_dir / self.entry.id / tag
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / asset["name"]
        self._download(asset["browser_download_url"], target, asset.get("size", 0))
        binary = self._unpack(target, folder, inst.inner)
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        subprocess.run(["xattr", "-d", "com.apple.quarantine", str(binary)], capture_output=True)
        return [str(binary), *inst.args], "download"

    def _download(self, url: str, target: Path, size: int) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp, open(target, "wb") as out:
            total = size or int(resp.headers.get("Content-Length") or 0)
            got = 0
            while True:
                if self._cancel.is_set():
                    raise InstallError("Cancelled")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                mb = got / 1e6
                self.progress.emit(got / total if total else -1,
                                   f"Downloading… {mb:.1f} of {total / 1e6:.0f} MB" if total else f"Downloading… {mb:.1f} MB")
        if total and target.stat().st_size != total:
            raise InstallError("the download was incomplete")

    def _unpack(self, path: Path, folder: Path, inner: str) -> Path:
        name = path.name.lower()
        if name.endswith((".tar.gz", ".tgz", ".tar", ".tar.xz")):
            self.progress.emit(-1, "Unpacking…")
            with tarfile.open(path) as tar:
                tar.extractall(folder, filter="data")
            path.unlink()
        elif name.endswith(".zip"):
            self.progress.emit(-1, "Unpacking…")
            with zipfile.ZipFile(path) as z:
                for member in z.namelist():
                    if member.startswith("/") or ".." in Path(member).parts:
                        raise InstallError("unsafe archive")
                z.extractall(folder)
            path.unlink()
        else:
            return path  # a plain executable
        candidates = [p for p in folder.rglob("*") if p.is_file()]
        if inner:
            candidates = [p for p in candidates if re.search(inner, p.name)]
        else:
            candidates = [p for p in candidates if p.suffix.lower() not in {".txt", ".md", ".nnue", ".pdf", ".html"}]
        if not candidates:
            raise InstallError("couldn't find the engine inside the download")
        return max(candidates, key=lambda p: p.stat().st_size)
