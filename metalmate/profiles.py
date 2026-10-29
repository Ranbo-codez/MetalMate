"""Saved board calibrations ("board profiles"), one per piece set / board theme."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .vision import BoardProfile, Recognition, recognize


@dataclass
class ProfileMeta:
    id: str
    name: str
    created: float
    updated: float

    @property
    def created_text(self) -> str:
        return time.strftime("%d %b %Y", time.localtime(self.created))


def plausibility(rec: Recognition) -> float | None:
    """How believable a recognition is as a real chess position (None = impossible).
    Works for either orientation."""
    flat = [s for row in rec.grid for s in row]
    if flat.count("K") != 1 or flat.count("k") != 1:
        return None
    if flat.count("P") > 8 or flat.count("p") > 8:
        return None
    if sum(s.isupper() for s in flat) > 16 or sum(s.islower() for s in flat) > 16:
        return None
    if any(s in "Pp" for s in rec.grid[0] + rec.grid[7]):
        return None
    occupied = rec.margin[np.array([[s != "." for s in row] for row in rec.grid])]
    return float(np.mean(np.log(np.clip(occupied, 1.0, 50.0)))) if occupied.size else 0.0


class ProfileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = root / "index.json"
        self._cache: dict[str, BoardProfile] = {}
        self._metas = self._read_index()

    def _read_index(self) -> dict[str, ProfileMeta]:
        try:
            raw = json.loads(self._index_path.read_text())
            return {d["id"]: ProfileMeta(**d) for d in raw}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _write_index(self) -> None:
        tmp = self._index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(m) for m in self._metas.values()], indent=2))
        tmp.replace(self._index_path)

    def list(self) -> list[ProfileMeta]:
        return sorted(self._metas.values(), key=lambda m: -m.updated)

    def get(self, profile_id: str | None) -> ProfileMeta | None:
        return self._metas.get(profile_id) if profile_id else None

    def preview_path(self, profile_id: str) -> Path:
        return self.root / f"{profile_id}.jpg"

    def load(self, profile_id: str | None) -> BoardProfile | None:
        if not profile_id or profile_id not in self._metas:
            return None
        if profile_id not in self._cache:
            profile = BoardProfile.load(self.root / f"{profile_id}.npz")
            if profile is None:
                return None
            self._cache[profile_id] = profile
        return self._cache[profile_id]

    def save(self, profile: BoardProfile, name: str, preview: np.ndarray, profile_id: str | None = None) -> ProfileMeta:
        now = time.time()
        if profile_id and profile_id in self._metas:
            meta = self._metas[profile_id]
            meta.updated = now
        else:
            meta = ProfileMeta(uuid.uuid4().hex[:12], name, now, now)
            self._metas[meta.id] = meta
        profile.save(self.root / f"{meta.id}.npz")
        img = Image.fromarray(preview)
        img.thumbnail((240, 240))
        img.save(self.preview_path(meta.id), quality=70)
        self._cache[meta.id] = profile
        self._write_index()
        return meta

    def rename(self, profile_id: str, name: str) -> None:
        if profile_id in self._metas:
            self._metas[profile_id].name = name
            self._write_index()

    def delete(self, profile_id: str) -> None:
        self._metas.pop(profile_id, None)
        self._cache.pop(profile_id, None)
        for ext in ("npz", "jpg"):
            (self.root / f"{profile_id}.{ext}").unlink(missing_ok=True)
        self._write_index()

    def pick_best(self, img: np.ndarray) -> tuple[str, Recognition] | None:
        """The profile that reads this screenshot as the most believable position."""
        best = None
        for meta in self.list():
            profile = self.load(meta.id)
            if profile is None:
                continue
            rec = recognize(img, profile)
            score = plausibility(rec)
            if score is not None and (best is None or score > best[0]):
                best = (score, meta.id, rec)
        return (best[1], best[2]) if best else None
