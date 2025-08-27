from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from .config import DATA_DIR


class History:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (DATA_DIR / "history.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def add(self, entry: Dict[str, Any]) -> None:
        entry = {**entry, "ts": datetime.utcnow().isoformat() + "Z"}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rows.append(json.loads(line))
        except FileNotFoundError:
            return []
        return rows[-limit:]

    def summarize(self, limit: int = 300) -> list[dict[str, Any]]:
        """Aggregate recent history into unique items (movie or episode) with last played method.

        Keying rules:
        - Movies: key = media_type:id
        - TV episodes: key = media_type:id:season:episode
        """
        rows = self.list(limit=limit)
        agg: dict[str, dict[str, Any]] = {}
        for r in rows:
            mid = r.get("id")
            mtype = r.get("media_type")
            if not mid or not mtype:
                continue
            ep = r.get("episode") or {}
            snum = ep.get("season") if isinstance(ep, dict) else None
            enum = ep.get("episode") if isinstance(ep, dict) else None
            key = f"{mtype}:{mid}:{snum or 0}:{enum or 0}"
            cur = agg.get(key, {
                "id": mid,
                "media_type": mtype,
                "title": r.get("title"),
                "poster_url": r.get("poster_url"),
                "backdrop_url": r.get("backdrop_url"),
                "release_year": r.get("release_year"),
                "vote_average": r.get("vote_average"),
                "episode": {"season": snum, "episode": enum} if (snum and enum) else None,
                "last_method": None,
                "ts": r.get("ts"),
                "last_play_ts": None,
                "source": r.get("source"),
            })
            # Update metadata if present
            if r.get("title"):
                cur["title"] = r.get("title")
            if r.get("poster_url"):
                cur["poster_url"] = r.get("poster_url")
            if r.get("backdrop_url"):
                cur["backdrop_url"] = r.get("backdrop_url")
            if r.get("release_year") is not None:
                cur["release_year"] = r.get("release_year")
            if r.get("vote_average") is not None:
                cur["vote_average"] = r.get("vote_average")
            if isinstance(r.get("episode"), dict):
                cur["episode"] = r.get("episode")
            # Track last play method
            if r.get("action") == "play" and r.get("method"):
                cur["last_method"] = r.get("method")
                cur["last_play_ts"] = r.get("ts")
            # Always update last seen timestamp
            cur["ts"] = r.get("ts") or cur.get("ts")
            agg[key] = cur
        out = list(agg.values())
        # Sort by last_play_ts (desc) then fallback to ts
        def sort_key(x: dict[str, Any]):
            return (x.get("last_play_ts") or x.get("ts") or "")
        out.sort(key=sort_key, reverse=True)
        return out
