from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests
from pydantic import BaseModel, Field
from urllib.parse import quote

TORBOX_BASE = "https://stremio.torbox.app"

DEFAULT_HEADERS = {
    "User-Agent": os.environ.get(
        "CINE_HTTP_UA",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": os.environ.get("CINE_HTTP_LANG", "en-US,en;q=0.9"),
    "Connection": "keep-alive",
}


def _maybe_proxy(url: str) -> str:
    """If CINE_PROXY_PREFIX is set and URL targets TorBox, wrap it.

    Expects prefix like: https://host/path?destination=
    """
    try:
        pref = os.environ.get("CINE_PROXY_PREFIX")
        if not pref:
            return url
        host = url.split("//", 1)[-1].split("/", 1)[0]
        if host.endswith("torbox.app") or host == "stremio.torbox.app":
            return f"{pref}{quote(url, safe=':/?&=%')}"
    except Exception:
        pass
    return url


class TorboxStream(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    url: str
    behaviorHints: Dict[str, Any] = Field(default_factory=dict)
    size_bytes: Optional[int] = None
    filename: Optional[str] = None

    def display(self) -> str:
        parts: List[str] = []
        # Prefer torrent filename if available
        if self.filename:
            parts.append(self.filename.replace("\n", " ").replace("\\n", " "))
        # Fallbacks
        if not parts and self.name:
            parts.append(self.name.replace("\n", " ").replace("\\n", " "))
        if not parts and self.title:
            parts.append(self.title.replace("\n", " ").replace("\\n", " "))
        if not parts:
            parts.append(self.url.split("/", 3)[-1][:40])
        label = " | ".join(parts)
        if isinstance(self.size_bytes, int) and self.size_bytes > 0:
            label += f"  ({_fmt_size(self.size_bytes)})"
        return label


def _torbox_url(api_key: str, media_type: str, imdb_id: str, season: Optional[int] = None, episode: Optional[int] = None) -> str:
    mt = media_type.lower().strip()
    if mt == "movie":
        return _maybe_proxy(f"{TORBOX_BASE}/{api_key}/stream/movie/{imdb_id}.json")
    if mt == "tv":
        if season is None or episode is None:
            raise ValueError("season and episode are required for tv")
        return _maybe_proxy(f"{TORBOX_BASE}/{api_key}/stream/series/{imdb_id}:{season}:{episode}.json")
    raise ValueError("media_type must be 'movie' or 'tv'")


def get_streams(api_key: str, media_type: str, imdb_id: str, *, season: Optional[int] = None, episode: Optional[int] = None, timeout: int = 15) -> List[TorboxStream]:
    url = _torbox_url(api_key, media_type, imdb_id, season, episode)
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    out: List[TorboxStream] = []
    for s in data.get("streams", []):
        u = s.get("url") or s.get("file") or s.get("src")
        if not isinstance(u, str):
            continue
        size_val = s.get("size")
        size_bytes: Optional[int] = None
        try:
            if isinstance(size_val, str) and size_val.isdigit():
                size_bytes = int(size_val)
            elif isinstance(size_val, (int, float)):
                size_bytes = int(size_val)
        except Exception:
            size_bytes = None
        # Derive filename from behaviorHints or description
        fname = None
        try:
            bh = s.get("behaviorHints") or {}
            if isinstance(bh, dict) and isinstance(bh.get("filename"), str):
                fname = bh.get("filename")
            if not fname and isinstance(s.get("description"), str):
                desc = s.get("description")
                # crude extract: look for 'filename:' token
                lower = desc.lower()
                if "filename:" in lower:
                    i = lower.index("filename:") + len("filename:")
                    chunk = desc[i:].split("\n", 1)[0].split("\\n", 1)[0].strip()
                    if chunk:
                        fname = chunk
        except Exception:
            fname = None

        out.append(
            TorboxStream(
                name=s.get("name"),
                title=s.get("title"),
                description=s.get("description"),
                url=u,
                behaviorHints=s.get("behaviorHints") or {},
                size_bytes=size_bytes,
                filename=fname,
            )
        )
    return out


def _fmt_size(n: int) -> str:
    try:
        # Use binary units for familiarity
        step = 1024.0
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(n)
        for u in units:
            if size < step or u == units[-1]:
                if u == "B":
                    return f"{int(size)} {u}"
                return f"{size:.1f} {u}"
            size /= step
    except Exception:
        pass
    return f"{n} B"
