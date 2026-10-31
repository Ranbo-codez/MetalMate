"""Suggested engines: strong, well-known UCI engines, with how to install each on a Mac.

Ratings are CCRL Blitz (computerchess.org.uk/ccrl/404, October 2026). They come from engine-vs-engine
games on fixed hardware and aren't comparable with human ratings. Engines whose authors don't
publish a macOS build are listed with their website only.

Everything installs without Homebrew: engines are downloaded from their authors' GitHub releases or,
when the authors publish no Mac build, as Homebrew's prebuilt package ("bottle") fetched directly.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass, field

RATING_SOURCE = "CCRL Blitz, Oct 2026"


@dataclass(frozen=True)
class Installer:
    kind: str                       # "github" | "bottle"
    formula: str = ""               # bottle: Homebrew formula name
    binary: str = ""                # bottle: the engine's path inside the package, e.g. "bin/stockfish"
    deps: tuple = ()                # bottle: formulas whose libraries the engine needs (e.g. readline)
    repo: str = ""                  # github: owner/name
    assets: tuple = ()              # github: ((arch, regex), ...) for the release asset
    inner: str = ""                 # github archives: regex for the engine binary inside
    args: tuple = ()                # extra command-line arguments (e.g. GNU Chess needs --uci); for
                                    # bottles, "{keg}" is the unpacked package and * is matched on disk

    def asset_pattern(self, arch: str) -> str | None:
        for a, pattern in self.assets:
            if a in (arch, "any"):
                return pattern
        return None


@dataclass(frozen=True)
class CatalogEngine:
    id: str
    name: str
    version: str
    author: str
    elo: int | None
    style: str
    license: str
    website: str
    blurb: str
    installers: tuple = field(default=())
    size_mb: int | None = None
    rating_note: str = ""           # where `elo` comes from, if not CCRL

    def installers_for(self, arch: str | None = None) -> list[Installer]:
        arch = arch or machine_arch()
        out = []
        for inst in self.installers:
            if (inst.kind == "bottle" and arch == "arm64") or inst.asset_pattern(arch):
                out.append(inst)
        return out

    @property
    def bundled(self) -> bool:
        return any(i.kind == "bundled" for i in self.installers)

    @property
    def mac_build(self) -> bool:
        return bool(self.installers_for())


def machine_arch() -> str:
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def bottle(formula: str, binary: str, deps: tuple = (), args: tuple = ()) -> Installer:
    return Installer("bottle", formula=formula, binary=binary, deps=deps, args=args)


def github(repo: str, arm64: str | None = None, x86_64: str | None = None, inner: str = "",
           universal: str | None = None) -> Installer:
    assets = []
    if universal:
        assets.append(("any", universal))
    if arm64:
        assets.append(("arm64", arm64))
    if x86_64:
        assets.append(("x86_64", x86_64))
    return Installer("github", repo=repo, assets=tuple(assets), inner=inner)


CATALOG: tuple[CatalogEngine, ...] = (
    CatalogEngine(
        "stockfish", "Stockfish", "19", "The Stockfish developers", 3804, "Alpha-beta search · NNUE", "GPL-3.0",
        "https://stockfishchess.org",
        "The strongest chess engine in the world, and the one every other engine is measured against.",
        (github("official-stockfish/Stockfish", universal=r"macos-universal\.tar\.gz$",
                inner=r"stockfish-macos-universal$"),
         bottle("stockfish", "bin/stockfish")),
        size_mb=82),
    CatalogEngine(
        "plentychess", "PlentyChess", "8.0", "Yoshie2000", 3774, "Alpha-beta search · NNUE", "GPL-3.0",
        "https://github.com/Yoshie2000/PlentyChess",
        "Joint second on CCRL. A young engine that climbed fast with a self-trained neural network.",
        (github("Yoshie2000/PlentyChess", arm64=r"macos-neon$"),), size_mb=54),
    CatalogEngine(
        "viridithas", "Viridithas", "20.0", "Cosmo Bobak", 3748, "Alpha-beta search · NNUE", "AGPL-3.0",
        "https://github.com/cosmobobak/viridithas",
        "A “superhuman” Rust engine whose network is trained purely on its own games.",
        (github("cosmobobak/viridithas", arm64=r"macos-aarch64$"),), size_mb=57),
    CatalogEngine(
        "stormphrax", "Stormphrax", "8.0", "Ciekce", 3745, "Alpha-beta search · NNUE", "GPL-3.0",
        "https://github.com/Ciekce/Stormphrax",
        "Network trained from zero knowledge: it learned chess entirely from its own play.",
        (github("Ciekce/Stormphrax", arm64=r"apple-m1$"),), size_mb=57),
    CatalogEngine(
        "halogen", "Halogen", "16", "Kieren Pearson", 3721, "Alpha-beta search · NNUE", "GPL-3.0",
        "https://github.com/KierenP/Halogen",
        "A compact, fast C++ engine. The smallest download of the strong engines.",
        (github("KierenP/Halogen", arm64=r"macos-arm64-neon-dotprod$", x86_64=r"macos-x86_64-avx2$"),), size_mb=20),
    CatalogEngine(
        "lc0", "Leela Chess Zero", "0.32", "The LCZero authors", 3696, "Neural network · MCTS", "GPL-3.0",
        "https://lczero.org",
        "AlphaZero-style: a deep network instead of brute-force search. Plays a distinctly human, "
        "positional game. Strength depends heavily on your Mac's GPU.",
        (bottle("lc0", "libexec/lc0", args=("--weights={keg}/libexec/*.pb.gz",)),), size_mb=20),
    CatalogEngine(
        "gnuchess", "GNU Chess", "6.3", "Free Software Foundation", 2833, "Classical alpha-beta", "GPL-3.0",
        "https://www.gnu.org/software/chess/",
        "The classic free engine. Much weaker than modern engines, which makes it a friendlier sparring "
        "partner.",
        (bottle("gnu-chess", "bin/gnuchess", deps=("readline",), args=("--uci",)),), size_mb=27),
    # No macOS builds published: listed so you know they exist.
    CatalogEngine("obsidian", "Obsidian", "16.0", "Gabriele Lombardo", 3774, "Alpha-beta search · NNUE", "GPL-3.0",
                  "https://github.com/gab8192/Obsidian", "Joint second on CCRL, from Italy."),
    CatalogEngine("berserk", "Berserk", "14", "Jay Honnold", 3760, "Alpha-beta search · NNUE", "GPL-3.0",
                  "https://github.com/jhonnold/berserk", "A long-time top-ten engine written in C."),
    CatalogEngine("alexandria", "Alexandria", "9.1", "PGG106", 3755, "Alpha-beta search · NNUE", "GPL-3.0",
                  "https://github.com/PGG106/Alexandria", "Bitboard engine with a strong NNUE."),
    CatalogEngine("caissa", "Caissa", "2.0", "Michał Witanowski", 3750, "Alpha-beta search · NNUE", "MIT",
                  "https://github.com/Witek902/Caissa", "Strong and permissively licensed."),
    CatalogEngine("ethereal", "Ethereal", "14.25", "Andrew Grant", 3723, "Alpha-beta search · NNUE", "GPL-3.0",
                  "https://github.com/AndyGrant/Ethereal", "Influential engine whose ideas shaped many others."),
)


def entry(catalog_id: str) -> CatalogEngine | None:
    return next((e for e in CATALOG if e.id == catalog_id), None)
