from __future__ import annotations

import shutil
import subprocess
from typing import Any, Dict, List, Optional
import os

import requests
from urllib.parse import quote
from pydantic import BaseModel, Field


TORRENTIO_BASE = "https://torrentio.strem.fun"

DEFAULT_HEADERS = {
    "User-Agent": os.environ.get(
        "CINE_HTTP_UA",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": os.environ.get("CINE_HTTP_LANG", "en-US,en;q=0.9"),
    "Referer": "https://torrentio.strem.fun/",
    "Origin": "https://torrentio.strem.fun",
    "Connection": "keep-alive",
}


def _maybe_proxy(url: str) -> str:
    """If CINE_PROXY_PREFIX is set and URL targets Torrentio, wrap it.

    Expects prefix like: https://host/path?destination=
    """
    try:
        pref = os.environ.get("CINE_PROXY_PREFIX")
        if not pref:
            return url
        host = url.split("//", 1)[-1].split("/", 1)[0]
        if host.endswith("torrentio.strem.fun") or host == "torrentio.strem.fun":
            return f"{pref}{quote(url, safe=':/?&=%')}"
    except Exception:
        pass
    return url


class TorrentioStream(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    infoHash: str
    fileIdx: Optional[int] = None
    behaviorHints: Dict[str, Any] = Field(default_factory=dict)
    sources: List[str] = Field(default_factory=list)

    def display(self) -> str:
        parts: List[str] = []
        if self.name:
            parts.append(self.name.replace("\n", " "))
        if self.title:
            parts.append(self.title.replace("\n", " "))
        # Fallbacks
        if not parts:
            fn = self.behaviorHints.get("filename")
            if fn:
                parts.append(fn)
            else:
                parts.append(self.infoHash[:12])
        idx = f"idx={self.fileIdx}" if self.fileIdx is not None else "idx=?"
        return f"{ ' | '.join(parts) }  ({idx})"


def _torrentio_url(media_type: str, imdb_id: str, season: Optional[int] = None, episode: Optional[int] = None) -> str:
    mt = media_type.lower().strip()
    if mt == "movie":
        return _maybe_proxy(f"{TORRENTIO_BASE}/stream/movie/{imdb_id}.json")
    if mt == "tv":
        if season is None or episode is None:
            raise ValueError("season and episode are required for tv")
        # Torrentio expects series path with imdb:season:episode
        return _maybe_proxy(f"{TORRENTIO_BASE}/stream/series/{imdb_id}:{season}:{episode}.json")
    raise ValueError("media_type must be 'movie' or 'tv'")


def get_streams(media_type: str, imdb_id: str, *, season: Optional[int] = None, episode: Optional[int] = None, timeout: int = 15) -> List[TorrentioStream]:
    url = _torrentio_url(media_type, imdb_id, season, episode)
    # First try with default headers
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    # If forbidden, retry with an alternate UA
    if r.status_code == 403:
        alt_headers = DEFAULT_HEADERS.copy()
        alt_headers["User-Agent"] = os.environ.get(
            "CINE_HTTP_UA_ALT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        )
        r = requests.get(url, headers=alt_headers, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    out: List[TorrentioStream] = []
    for s in data.get("streams", []):
        out.append(
            TorrentioStream(
                name=s.get("name"),
                title=s.get("title"),
                infoHash=s.get("infoHash"),
                fileIdx=s.get("fileIdx"),
                behaviorHints=s.get("behaviorHints") or {},
                sources=s.get("sources") or [],
            )
        )
    return out


def build_magnet(info_hash: str, *, display_name: Optional[str] = None, sources: Optional[List[str]] = None) -> str:
    # Base magnet
    magnet = f"magnet:?xt=urn:btih:{info_hash}"
    # Add display name
    if display_name:
        try:
            from urllib.parse import quote_plus

            magnet += f"&dn={quote_plus(display_name)}"
        except Exception:
            pass
    # Add trackers from sources
    if sources:
        try:
            from urllib.parse import quote

            for src in sources:
                if isinstance(src, str) and src.startswith("tracker:"):
                    tr = src.split("tracker:", 1)[1]
                    magnet += f"&tr={quote(tr, safe=':/?&=%')}"
        except Exception:
            pass
    return magnet


def has_webtorrent() -> bool:
    return shutil.which("webtorrent") is not None


def launch_webtorrent(
    magnet: str,
    player: str,
    *,
    file_idx: Optional[int] = None,
    interactive: bool = False,
    playlist: bool = False,
    out_dir: Optional[str] = None,
) -> subprocess.Popen | None:
    if not has_webtorrent():
        return None
    player_flag = f"--{player}"
    cmd = ["webtorrent", magnet, player_flag]
    if out_dir:
        cmd += ["--out", out_dir]
    if file_idx is not None:
        cmd += ["--select", str(file_idx)]
    if interactive:
        cmd.append("--interactive-select")
    if playlist:
        cmd.append("--playlist")
    # Do not block; let player open
    return subprocess.Popen(cmd)


def download_webtorrent(magnet: str, out_dir: str, *, file_idx: Optional[int] = None, interactive: bool = False) -> subprocess.Popen | None:
    """Download a torrent to the specified directory using webtorrent-cli.

    This does not launch any player. It spawns the process and returns Popen.
    """
    if not has_webtorrent():
        return None
    cmd = ["webtorrent", magnet, "--out", out_dir]
    if file_idx is not None:
        cmd += ["--select", str(file_idx)]
    if interactive:
        cmd.append("--interactive-select")
    return subprocess.Popen(cmd)
