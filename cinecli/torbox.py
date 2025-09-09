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

    def display(self) -> str:
        parts: List[str] = []
        if self.name:
            parts.append(self.name.replace("\n", " "))
        if self.title:
            parts.append(self.title.replace("\n", " "))
        if not parts:
            parts.append(self.url.split("/", 3)[-1][:40])
        return " | ".join(parts)


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
        out.append(
            TorboxStream(
                name=s.get("name"),
                title=s.get("title"),
                description=s.get("description"),
                url=u,
                behaviorHints=s.get("behaviorHints") or {},
            )
        )
    return out
