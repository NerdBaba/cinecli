from __future__ import annotations

import os
from typing import List, Optional, Dict, Any

import requests
from pydantic import BaseModel, Field
from urllib.parse import quote


class DirectStream(BaseModel):
    url: str
    name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    behaviorHints: Dict[str, Any] = Field(default_factory=dict)
    size_bytes: Optional[int] = None
    filename: Optional[str] = None

    def display(self) -> str:
        parts: List[str] = []
        if self.filename:
            parts.append(self.filename.replace("\n", " ").replace("\\n", " "))
        if not parts and self.name:
            parts.append(self.name.replace("\n", " ").replace("\\n", " "))
        if not parts and self.title:
            parts.append(self.title.replace("\n", " ").replace("\\n", " "))
        if not parts:
            parts.append(self.url.split("/", 3)[-1][:40])
        label = " | ".join(parts)
        if isinstance(self.size_bytes, int) and self.size_bytes > 0:
            # humanize
            size = float(self.size_bytes)
            units = ["B","KB","MB","GB","TB"]
            for u in units:
                if size < 1024 or u == units[-1]:
                    label += f"  ({int(size) if u=='B' else f'{size:.1f}'} {u})"
                    break
                size /= 1024.0
        return label


def _maybe_proxy(url: str) -> str:
    """Wrap URL behind global proxy if CINE_PROXY_PREFIX is set.

    Unlike provider-specific wrappers, this applies to any domain.
    Expects prefix like: https://host/path?destination=
    """
    try:
        pref = os.environ.get("CINE_PROXY_PREFIX")
        if not pref:
            return url
        return f"{pref}{quote(url, safe=':/?&=%')}"
    except Exception:
        return url


def _safe_get_json(url: str, *, timeout: int = 12) -> dict:
    r = requests.get(_maybe_proxy(url), timeout=timeout, headers={
        "User-Agent": os.environ.get(
            "CINE_HTTP_UA",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": os.environ.get("CINE_HTTP_LANG", "en-US,en;q=0.9"),
    })
    r.raise_for_status()
    return r.json()


def _manifest_parent(manifest_url: str) -> str:
    # Strip trailing /manifest.json and any trailing slash
    if manifest_url.endswith("/manifest.json"):
        return manifest_url[: -len("/manifest.json")].rstrip("/")
    # Allow users to provide a parent base already
    return manifest_url.rstrip("/")


def _extract_direct_streams(data: dict) -> List[DirectStream]:
    out: List[DirectStream] = []
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
        fname = None
        try:
            bh = s.get("behaviorHints") or {}
            if isinstance(bh, dict) and isinstance(bh.get("filename"), str):
                fname = bh.get("filename")
            if not fname and isinstance(s.get("description"), str):
                desc = s.get("description")
                lower = desc.lower()
                if "filename:" in lower:
                    i = lower.index("filename:") + len("filename:")
                    chunk = desc[i:].split("\n", 1)[0].split("\\n", 1)[0].strip()
                    if chunk:
                        fname = chunk
        except Exception:
            fname = None
        out.append(
            DirectStream(
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


def get_torrentio_tb_streams(torbox_api_key: str, media_type: str, imdb_id: str, *, season: Optional[int] = None, episode: Optional[int] = None, timeout: int = 12) -> List[DirectStream]:
    mt = media_type.lower().strip()
    base = f"https://torrentio.strem.fun/torbox={torbox_api_key}"
    if mt == "movie":
        url = f"{base}/stream/movie/{imdb_id}.json"
    elif mt == "tv":
        if season is None or episode is None:
            raise ValueError("season and episode are required for tv")
        url = f"{base}/stream/series/{imdb_id}:{season}:{episode}.json"
    else:
        raise ValueError("media_type must be 'movie' or 'tv'")
    data = _safe_get_json(url, timeout=timeout)
    return _extract_direct_streams(data)


def get_manifest_streams(manifest_url: str, media_type: str, imdb_id: str, *, season: Optional[int] = None, episode: Optional[int] = None, timeout: int = 12) -> List[DirectStream]:
    mt = media_type.lower().strip()
    parent = _manifest_parent(manifest_url)
    if mt == "movie":
        url = f"{parent}/stream/movie/{imdb_id}.json"
    elif mt == "tv":
        if season is None or episode is None:
            raise ValueError("season and episode are required for tv")
        url = f"{parent}/stream/series/{imdb_id}:{season}:{episode}.json"
    else:
        raise ValueError("media_type must be 'movie' or 'tv'")
    data = _safe_get_json(url, timeout=timeout)
    return _extract_direct_streams(data)
