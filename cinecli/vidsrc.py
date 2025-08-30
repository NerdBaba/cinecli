from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import requests
from urllib.parse import quote

DEFAULT_TIMEOUT = 8

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

VALID_VIDSRC_DOMAINS = [
    # Ordered by likelihood of being up
    "vidsrc.xyz",
]


def _maybe_proxy(url: str) -> str:
    """If CINE_PROXY_PREFIX is set and URL targets a VidSrc domain, wrap it.

    Expects prefix like: https://host/path?destination=
    """
    try:
        pref = os.environ.get("CINE_PROXY_PREFIX")
        if not pref:
            return url
        # Only proxy VidSrc domains
        host = re.sub(r"^https?://", "", url).split("/", 1)[0]
        if any(host.endswith(d) or host == d for d in VALID_VIDSRC_DOMAINS):
            return f"{pref}{quote(url, safe=':/?&=%')}"
    except Exception:
        pass
    return url


@dataclass
class StreamCandidate:
    url: str
    kind: str  # m3u8 | mp4 | other
    server_hash: Optional[str] = None
    rcp_host: Optional[str] = None
    nested_url: Optional[str] = None


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )
    return s


def _candidate_embed_urls(media_type: str, tmdb_id: int | str, season: int | None, episode: int | None) -> List[str]:
    ms = str(media_type).lower()
    mid = str(tmdb_id)
    urls: List[str] = []
    for dom in VALID_VIDSRC_DOMAINS:
        base = f"https://{dom}"
        if ms == "movie":
            urls.extend(
                [
                    f"{base}/embed/movie/{mid}",
                    f"{base}/embed/movie?tmdb={mid}",
                    f"{base}/embed/?tmdb={mid}",
                ]
            )
        else:
            if season and episode:
                urls.extend(
                    [
                        f"{base}/embed/tv/{mid}/{season}-{episode}",
                        f"{base}/embed/tv?tmdb={mid}&season={season}&episode={episode}",
                        f"{base}/embed/tv?tmdb={mid}&s={season}&e={episode}",
                    ]
                )
            else:
                # fallback variants if season/episode unknown
                urls.extend(
                    [
                        f"{base}/embed/tv/{mid}",
                        f"{base}/embed/tv?tmdb={mid}",
                    ]
                )
    # Ensure uniqueness while preserving order
    seen = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            unique_urls.append(u)
            seen.add(u)
    return unique_urls


def _extract_hashes(html: str) -> List[str]:
    hashes: List[str] = []
    # data-hash="..." or data-hash='...'
    for m in re.finditer(r"data-hash=\"([^\"]+)\"", html):
        hashes.append(m.group(1))
    for m in re.finditer(r"data-hash='([^']+)'", html):
        hashes.append(m.group(1))
    # Sometimes alternative attribute used
    for m in re.finditer(r"data-id=\"([^\"]{16,})\"", html):
        hashes.append(m.group(1))
    # Deduplicate
    out: List[str] = []
    seen = set()
    for h in hashes:
        if h and h not in seen:
            out.append(h)
            seen.add(h)
    return out


def _find_rcp_hosts(embed_html: str, embed_host: str) -> List[str]:
    hosts = []
    # Look for explicit rcp host references in the embed HTML (e.g., cloudnestra.com)
    for m in re.finditer(r"https?://([a-z0-9.-]+)/rcp/", embed_html, flags=re.I):
        hosts.append(m.group(1))
    # Always try the embed host itself as a fallback
    hosts.append(embed_host)
    # Known common host from field reports
    hosts.append("cloudnestra.com")
    # Dedup while preserving order
    seen = set()
    uniq = []
    for h in hosts:
        if h and h not in seen:
            uniq.append(h)
            seen.add(h)
    return uniq


def _extract_nested_src(html: str) -> Optional[str]:
    # Patterns like: src: 'https://...'
    m = re.search(r"src\s*:\s*'([^']+)'", html)
    if m:
        return m.group(1)
    m = re.search(r'\bsrc\s*:\s*"([^"]+)"', html)
    if m:
        return m.group(1)
    # Direct iframe tag
    m = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
    if m:
        return m.group(1)
    return None


def _extract_child_candidates(html: str) -> List[str]:
    """Extract potential child URLs to follow (iframe-like or script-declared sources)."""
    urls: List[str] = []
    # iframe tags
    for m in re.finditer(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, flags=re.I):
        urls.append(m.group(1))
    # src: '...'
    for m in re.finditer(r"\bsrc\s*:\s*'([^']+)'", html):
        urls.append(m.group(1))
    for m in re.finditer(r'\bsrc\s*:\s*"([^"]+)"', html):
        urls.append(m.group(1))
    # file: "...m3u8" or mp4 – add as potential direct
    for m in re.finditer(r'\bfile\s*:\s*"(https?://[^\"]+)"', html, flags=re.I):
        urls.append(m.group(1))
    # source src="..."
    for m in re.finditer(r'<source[^>]+src=["\']([^"\']+)["\']', html, flags=re.I):
        urls.append(m.group(1))
    # data-src attributes
    for m in re.finditer(r'data-src=["\']([^"\']+)["\']', html, flags=re.I):
        urls.append(m.group(1))
    # Deduplicate preserving order
    seen = set()
    out: List[str] = []
    for u in urls:
        if u and u not in seen:
            out.append(u)
            seen.add(u)
    return out


def _absolute_url(base_host: str, maybe_rel: str) -> str:
    if maybe_rel.startswith("http://") or maybe_rel.startswith("https://"):
        return maybe_rel
    if maybe_rel.startswith("//"):
        return f"https:{maybe_rel}"
    # join with https scheme and host
    if maybe_rel.startswith("/"):
        return f"https://{base_host}{maybe_rel}"
    return f"https://{base_host}/{maybe_rel}"


def _extract_stream_urls(html: str) -> List[Tuple[str, str]]:
    # Return list of (url, kind)
    results: List[Tuple[str, str]] = []
    for m in re.finditer(r"https?://[^\"'\s]+\.m3u8[^\"'\s]*", html, flags=re.I):
        results.append((m.group(0), "m3u8"))
    for m in re.finditer(r"https?://[^\"'\s]+\.mp4[^\"'\s]*", html, flags=re.I):
        results.append((m.group(0), "mp4"))
    # Sometimes JSON-like sources: "file":"...m3u8"
    for m in re.finditer(r'"file"\s*:\s*"(https?://[^\"]+)"', html, flags=re.I):
        url = m.group(1)
        kind = "m3u8" if ".m3u8" in url else ("mp4" if ".mp4" in url else "other")
        results.append((url, kind))
    # Deduplicate preserving order
    seen = set()
    uniq: List[Tuple[str, str]] = []
    for u, k in results:
        key = (u, k)
        if key not in seen:
            uniq.append((u, k))
            seen.add(key)
    return uniq


def scrape_vidsrc(
    media_type: str,
    tmdb_id: int | str,
    season: int | None = None,
    episode: int | None = None,
    max_hosts: int = 3,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[StreamCandidate]:
    """Scrape VidSrc embeds to discover direct stream URLs (m3u8/mp4).

    Returns a list of StreamCandidate with source metadata. Best-effort only.
    """
    sess = _session()

    save_html = str(os.environ.get("CINE_SAVE_VIDSRC_HTML", "")).lower() in {"1", "true", "yes", "on"}

    candidates: List[StreamCandidate] = []
    tried = 0

    for embed_url in _candidate_embed_urls(media_type, tmdb_id, season, episode):
        if tried >= max_hosts:
            break
        tried += 1
        try:
            r = sess.get(_maybe_proxy(embed_url), timeout=timeout)
        except Exception:
            continue
        if r.status_code != 200 or not r.text:
            continue
        embed_html = r.text
        if save_html:
            try:
                with open(f"/tmp/vidsrc_embed_{int(time.time())}.html", "w", encoding="utf-8") as f:
                    f.write(embed_html)
            except Exception:
                pass
        # Build an exploration queue: rcp URLs from hashes + any child-like URLs from embed page
        hashes = _extract_hashes(embed_html)
        embed_host = re.sub(r"^https?://", "", embed_url).split("/", 1)[0]
        rcp_hosts = _find_rcp_hosts(embed_html, embed_host)

        queue: List[Tuple[str, Optional[str], Optional[str], Optional[str]]] = []  # (url, referer, server_hash, rcp_host)
        visited: set[str] = set()

        for h in hashes:
            for host in rcp_hosts:
                queue.append((f"https://{host}/rcp/{h}", embed_url, h, host))

        # Also enqueue any iframe-like child references from the embed HTML itself
        for child in _extract_child_candidates(embed_html):
            queue.append((_absolute_url(embed_host, child), embed_url, None, None))

        pages = 0
        MAX_PAGES = 20
        while queue and pages < MAX_PAGES and not candidates:
            url, ref, h, host = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            headers = {"Referer": ref} if ref else {}
            # Add Origin header based on host if available to satisfy some CDNs
            try:
                # Prefer explicit rcp host, else referer host, else current url host
                origin_host = host or (re.sub(r"^https?://", "", ref).split("/", 1)[0] if ref else None) or re.sub(r"^https?://", "", url).split("/", 1)[0]
                if origin_host:
                    headers["Origin"] = f"https://{origin_host}"
            except Exception:
                pass
            try:
                resp = sess.get(_maybe_proxy(url), headers=headers, timeout=timeout)
            except Exception:
                continue
            pages += 1
            if resp.status_code != 200 or not resp.text:
                continue
            html = resp.text
            if save_html and pages <= 3:
                try:
                    with open(f"/tmp/vidsrc_crawl_{int(time.time())}.html", "w", encoding="utf-8") as f:
                        f.write(html)
                except Exception:
                    pass

            # 1) Extract direct stream URLs if present
            for url_found, kind in _extract_stream_urls(html):
                candidates.append(
                    StreamCandidate(
                        url=url_found,
                        kind=kind,
                        server_hash=h,
                        rcp_host=host,
                        nested_url=url,
                    )
                )
            if candidates:
                break

            # 2) Enqueue nested iframe-like URLs from this page
            # Determine base_host from current URL
            base_host = re.sub(r"^https?://", "", url).split("/", 1)[0]
            for child in _extract_child_candidates(html):
                try:
                    child_abs = _absolute_url(base_host, child)
                except Exception:
                    continue
                queue.append((child_abs, url, h, host))

            # 3) Also handle explicit nested src via src: '...'
            nested_src = _extract_nested_src(html)
            if nested_src:
                try:
                    nested_abs = _absolute_url(base_host, nested_src)
                    queue.append((nested_abs, url, h, host))
                except Exception:
                    pass
    return candidates
