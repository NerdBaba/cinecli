from __future__ import annotations

import argparse
import json
import sys
import shutil
import subprocess
import os
from typing import Optional

from .config import ConfigManager
from .history import History
from .tmdb import TMDBClient
from .ui import run_fzf, pick_from_strings, pick_with_preview
from .models import MediaType
from .vidsrc import scrape_vidsrc, StreamCandidate
from .torrentio import (
    get_streams as torrentio_get_streams,
    build_magnet as torrentio_build_magnet,
    launch_webtorrent as torrentio_launch,
    has_webtorrent as torrentio_has_webtorrent,
    download_webtorrent as torrentio_download,
    TorrentioStream,
)


def cmd_setup() -> int:
    cfg = ConfigManager()
    cfg.interactive_setup()
    return 0


def _download_with_vidsrc(cfg: ConfigManager, hist: History, *, tmdb_id: int, media_type_val: str, episode_payload: Optional[dict], title: str, poster_url: Optional[str], backdrop_url: Optional[str]) -> int:
    # Resolve streams via VidSrc
    if media_type_val == MediaType.movie.value:
        streams = scrape_vidsrc("movie", tmdb_id, timeout=10)
    else:
        if not episode_payload:
            print("No episode selected; cannot resolve TV streams.")
            return 0
        streams = scrape_vidsrc("tv", tmdb_id, season=episode_payload.get("season"), episode=episode_payload.get("episode"), timeout=10)
    if not streams:
        print("No streams found via VidSrc.")
        return 0
    # Prefer m3u8 over mp4
    def sort_key(it: StreamCandidate):
        pref = 0 if it.kind == "m3u8" else (1 if it.kind == "mp4" else 2)
        return (pref, len(it.url))
    best = sorted(streams, key=sort_key)[0]
    out_dir = _prompt_directory()
    if not out_dir:
        print("No directory provided.")
        return 0
    # Ensure yt-dlp exists
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        print("yt-dlp not found on PATH. Install it to enable VidSrc downloads.")
        print(f"URL: {best.url}")
        return 0
    # Build command
    output_tpl = os.path.join(out_dir, "%(title)s.%(ext)s")
    cmd = [ytdlp, best.url, "-o", output_tpl]
    if getattr(best, "nested_url", None):
        cmd += ["--referer", best.nested_url]
    print(f"Downloading with yt-dlp -> {output_tpl}")
    try:
        subprocess.Popen(cmd)
        _record_download(hist, media_id=tmdb_id, media_type=media_type_val, title=title, episode_payload=episode_payload, poster_url=poster_url, backdrop_url=backdrop_url, method="vidsrc", out_dir=out_dir)
    except Exception as e:
        print(f"Failed to launch yt-dlp: {e}")
    return 0


def _download_with_torrentio(cfg: ConfigManager, hist: History, tmdb: TMDBClient, *, tmdb_id: int, media_type_val: str, episode_payload: Optional[dict], title: str, poster_url: Optional[str], backdrop_url: Optional[str]) -> int:
    imdb_id = None
    try:
        if media_type_val == MediaType.movie.value:
            imdb_id = tmdb.movie_external_ids(tmdb_id).get("imdb_id")
        else:
            imdb_id = tmdb.tv_external_ids(tmdb_id).get("imdb_id")
    except Exception as e:
        print(f"Failed to fetch external IDs: {e}")
        return 0
    if not imdb_id:
        print("No IMDb ID found for item.")
        return 0
    try:
        if media_type_val == MediaType.movie.value:
            streams = torrentio_get_streams("movie", imdb_id, timeout=12)
        else:
            if not episode_payload:
                print("No episode selected; cannot resolve TV torrents.")
                return 0
            streams = torrentio_get_streams("tv", imdb_id, season=episode_payload.get("season"), episode=episode_payload.get("episode"), timeout=12)
    except Exception as e:
        print(f"Failed to fetch Torrentio streams: {e}")
        return 0
    if not streams:
        print("No Torrentio streams found.")
        return 0
    labels = [s.display() for s in streams]
    pick = pick_from_strings(labels, header="Torrentio Stream")
    if not pick:
        print("Nothing selected.")
        return 0
    try:
        idx = labels.index(pick)
    except ValueError:
        idx = 0
    chosen: TorrentioStream = streams[idx]
    display_name = chosen.behaviorHints.get("filename") or chosen.title or title
    magnet = torrentio_build_magnet(chosen.infoHash, display_name=display_name, sources=chosen.sources)
    if not torrentio_has_webtorrent():
        print("webtorrent-cli not found on PATH. Install with: npm i -g webtorrent-cli")
        print(f"Magnet: {magnet}")
        return 0
    out_dir = _prompt_directory()
    if not out_dir:
        print("No directory provided.")
        return 0
    print(f"Downloading with webtorrent -> {display_name}")
    try:
        torrentio_download(magnet, out_dir, file_idx=chosen.fileIdx, interactive=(chosen.fileIdx is None))
        _record_download(hist, media_id=tmdb_id, media_type=media_type_val, title=title, episode_payload=episode_payload, poster_url=poster_url, backdrop_url=backdrop_url, method="torrentio", out_dir=out_dir)
    except Exception as e:
        print(f"Failed to launch webtorrent download: {e}")
    return 0

def _choose_player(cfg: ConfigManager) -> Optional[str]:
    return cfg.player if shutil.which(cfg.player) else ("mpv" if shutil.which("mpv") else ("vlc" if shutil.which("vlc") else None))


def _record_play(hist: History, *, media_id: int, media_type: str, title: str, episode_payload: Optional[dict], poster_url: Optional[str], backdrop_url: Optional[str], method: str) -> None:
    hist.add(
        {
            "action": "play",
            "method": method,
            "id": media_id,
            "media_type": media_type,
            "title": title,
            "episode": episode_payload,
            "poster_url": poster_url,
            "backdrop_url": backdrop_url,
        }
    )


def _record_download(hist: History, *, media_id: int, media_type: str, title: str, episode_payload: Optional[dict], poster_url: Optional[str], backdrop_url: Optional[str], method: str, out_dir: str) -> None:
    hist.add(
        {
            "action": "download",
            "method": method,
            "id": media_id,
            "media_type": media_type,
            "title": title,
            "episode": episode_payload,
            "poster_url": poster_url,
            "backdrop_url": backdrop_url,
            "out_dir": out_dir,
        }
    )


def _pick_action() -> Optional[str]:
    options = [
        "Play with VidSrc",
        "Play with Torrentio",
        "Download with VidSrc",
        "Download with Torrentio",
        "Skip",
    ]
    sel = pick_from_strings(options, header="Action")
    if not sel:
        return None
    mapping = {
        "Play with VidSrc": "play_vidsrc",
        "Play with Torrentio": "play_torrentio",
        "Download with VidSrc": "download_vidsrc",
        "Download with Torrentio": "download_torrentio",
        "Skip": "skip",
    }
    return mapping.get(sel)


def _prompt_directory() -> Optional[str]:
    try:
        path = input("Download directory: ").strip()
    except KeyboardInterrupt:
        return None
    if not path:
        return None
    path = os.path.expanduser(path)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        print(f"Failed to create directory: {e}")
        return None
    return path


def _play_with_vidsrc(cfg: ConfigManager, hist: History, *, tmdb_id: int, media_type_val: str, episode_payload: Optional[dict], title: str, poster_url: Optional[str], backdrop_url: Optional[str]) -> int:
    # Resolve streams via VidSrc
    if media_type_val == MediaType.movie.value:
        streams = scrape_vidsrc("movie", tmdb_id, timeout=10)
    else:
        if not episode_payload:
            print("No episode selected; cannot resolve TV streams.")
            return 0
        streams = scrape_vidsrc("tv", tmdb_id, season=episode_payload.get("season"), episode=episode_payload.get("episode"), timeout=10)
    if not streams:
        print("No streams found via VidSrc.")
        return 0
    def sort_key(it: StreamCandidate):
        pref = 0 if it.kind == "m3u8" else (1 if it.kind == "mp4" else 2)
        return (pref, len(it.url))
    best = sorted(streams, key=sort_key)[0]
    player = _choose_player(cfg)
    if not player:
        print("No supported player (mpv/vlc) found on PATH.")
        print(f"URL: {best.url}")
        return 0
    print(f"Launching {player} -> {best.kind}: {best.url}")
    try:
        cmd = [player]
        if player == "mpv" and getattr(best, "nested_url", None):
            cmd.append(f"--referrer={best.nested_url}")
        cmd.append(best.url)
        subprocess.Popen(cmd)
        _record_play(hist, media_id=tmdb_id, media_type=media_type_val, title=title, episode_payload=episode_payload, poster_url=poster_url, backdrop_url=backdrop_url, method="vidsrc")
    except Exception as e:
        print(f"Failed to launch {player}: {e}")
    return 0


def _play_with_torrentio(cfg: ConfigManager, hist: History, tmdb: TMDBClient, *, tmdb_id: int, media_type_val: str, episode_payload: Optional[dict], title: str, poster_url: Optional[str], backdrop_url: Optional[str]) -> int:
    imdb_id = None
    try:
        if media_type_val == MediaType.movie.value:
            imdb_id = tmdb.movie_external_ids(tmdb_id).get("imdb_id")
        else:
            imdb_id = tmdb.tv_external_ids(tmdb_id).get("imdb_id")
    except Exception as e:
        print(f"Failed to fetch external IDs: {e}")
        return 0
    if not imdb_id:
        print("No IMDb ID found for item.")
        return 0
    try:
        if media_type_val == MediaType.movie.value:
            streams = torrentio_get_streams("movie", imdb_id, timeout=12)
        else:
            if not episode_payload:
                print("No episode selected; cannot resolve TV torrents.")
                return 0
            streams = torrentio_get_streams("tv", imdb_id, season=episode_payload.get("season"), episode=episode_payload.get("episode"), timeout=12)
    except Exception as e:
        print(f"Failed to fetch Torrentio streams: {e}")
        return 0
    if not streams:
        print("No Torrentio streams found.")
        return 0
    labels = [s.display() for s in streams]
    pick = pick_from_strings(labels, header="Torrentio Stream")
    if not pick:
        print("Nothing selected.")
        return 0
    try:
        idx = labels.index(pick)
    except ValueError:
        idx = 0
    chosen: TorrentioStream = streams[idx]
    display_name = chosen.behaviorHints.get("filename") or chosen.title or title
    magnet = torrentio_build_magnet(chosen.infoHash, display_name=display_name, sources=chosen.sources)
    player = _choose_player(cfg)
    if not player:
        print("No supported player (mpv/vlc) found on PATH.")
        print(f"Magnet: {magnet}")
        return 0
    if not torrentio_has_webtorrent():
        print("webtorrent-cli not found on PATH. Install with: npm i -g webtorrent-cli")
        print(f"Magnet: {magnet}")
        return 0
    print(f"Launching webtorrent -> {player} : {display_name}")
    try:
        torrentio_launch(
            magnet,
            player,
            file_idx=chosen.fileIdx,
            interactive=(chosen.fileIdx is None),
            playlist=False,
            out_dir=getattr(cfg, "webtorrent_tmp_dir", None),
        )
        _record_play(hist, media_id=tmdb_id, media_type=media_type_val, title=title, episode_payload=episode_payload, poster_url=poster_url, backdrop_url=backdrop_url, method="torrentio")
    except Exception as e:
        print(f"Failed to launch webtorrent: {e}")
    return 0


def cmd_dashboard(no_preview: bool = False) -> int:
    cfg = ConfigManager().load()
    tmdb = TMDBClient(cfg.tmdb_api_key)
    hist = History()

    sections = ["History", "Popular Movies", "Popular TV", "Search"]
    choice = pick_from_strings(sections, header="Dashboard")
    if not choice:
        return 0

    if choice == "History":
        items = hist.summarize(limit=300)
        if not items:
            print("No history yet.")
            return 0
        rows = []
        for it in items:
            title = it.get("title") or "Unknown"
            year = it.get("release_year")
            rating = it.get("vote_average")
            mtype = it.get("media_type")
            ep = it.get("episode") or {}
            last_method = it.get("last_method")
            label = ("🎬" if mtype == MediaType.movie.value else "📺") + f" {title}"
            if year:
                label += f" ({year})"
            if mtype == MediaType.tv.value and ep and ep.get("season") and ep.get("episode"):
                label += f"  S{int(ep.get('season')):02d}E{int(ep.get('episode')):02d}"
            if rating is not None:
                label += f"  ★{float(rating):.1f}"
            if last_method:
                label += f"  [last: {last_method}]"
            payload = {
                "id": it.get("id"),
                "media_type": mtype,
                "title": title,
                "poster_url": it.get("poster_url"),
                "backdrop_url": it.get("backdrop_url"),
                "season": (ep.get("season") if ep else None),
                "episode": (ep.get("episode") if ep else None),
                "last_method": last_method,
            }
            rows.append({"text": label, "payload": payload})
        sel = pick_with_preview(rows, header="History")
        if not sel:
            return 0
        media_type_val = sel.get("media_type")
        tmdb_id = int(sel.get("id"))
        title = sel.get("title") or ""
        ep_payload = None
        if media_type_val == MediaType.tv.value and sel.get("season") and sel.get("episode"):
            ep_payload = {"season": int(sel.get("season")), "episode": int(sel.get("episode"))}
        method = sel.get("last_method")
        action = _pick_action()
        if not action or action == "skip":
            print("Skipped.")
            return 0
        if action == "play_vidsrc":
            return _play_with_vidsrc(cfg, hist, tmdb_id=tmdb_id, media_type_val=media_type_val, episode_payload=ep_payload, title=title, poster_url=sel.get("poster_url"), backdrop_url=sel.get("backdrop_url"))
        if action == "play_torrentio":
            return _play_with_torrentio(cfg, hist, tmdb, tmdb_id=tmdb_id, media_type_val=media_type_val, episode_payload=ep_payload, title=title, poster_url=sel.get("poster_url"), backdrop_url=sel.get("backdrop_url"))
        if action == "download_vidsrc":
            return _download_with_vidsrc(cfg, hist, tmdb_id=tmdb_id, media_type_val=media_type_val, episode_payload=ep_payload, title=title, poster_url=sel.get("poster_url"), backdrop_url=sel.get("backdrop_url"))
        if action == "download_torrentio":
            return _download_with_torrentio(cfg, hist, tmdb, tmdb_id=tmdb_id, media_type_val=media_type_val, episode_payload=ep_payload, title=title, poster_url=sel.get("poster_url"), backdrop_url=sel.get("backdrop_url"))
        return 0

    elif choice == "Popular Movies":
        items = tmdb.movie_popular(page=1)
        if not items:
            print("No popular movies.")
            return 0
        selected = run_fzf(items, preview=(cfg.image_preview and not no_preview))
        if not selected:
            return 0
        # Lookup last method from history (if any)
        last_method = None
        for it in hist.summarize(limit=300):
            if it.get("media_type") == MediaType.movie.value and int(it.get("id")) == int(selected.id) and it.get("last_method"):
                last_method = it.get("last_method")
                break
        action = _pick_action()
        if not action or action == "skip":
            print("Skipped.")
            return 0
        if action == "play_vidsrc":
            return _play_with_vidsrc(cfg, hist, tmdb_id=selected.id, media_type_val=MediaType.movie.value, episode_payload=None, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
        if action == "play_torrentio":
            return _play_with_torrentio(cfg, hist, tmdb, tmdb_id=selected.id, media_type_val=MediaType.movie.value, episode_payload=None, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
        if action == "download_vidsrc":
            return _download_with_vidsrc(cfg, hist, tmdb_id=selected.id, media_type_val=MediaType.movie.value, episode_payload=None, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
        if action == "download_torrentio":
            return _download_with_torrentio(cfg, hist, tmdb, tmdb_id=selected.id, media_type_val=MediaType.movie.value, episode_payload=None, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
        return 0

    elif choice == "Search":
        # Prompted search with same preview behavior as other flows
        return cmd_search(None, no_preview=no_preview)

    elif choice == "Popular TV":
        items = tmdb.tv_popular(page=1)
        if not items:
            print("No popular TV shows.")
            return 0
        selected = run_fzf(items, preview=(cfg.image_preview and not no_preview))
        if not selected:
            return 0
        # Drill down to season/episode (same as search)
        tvd = tmdb.tv_details(selected.id)
        seasons = [s for s in tvd.get("seasons", []) if s.get("season_number", 0) > 0 and s.get("episode_count", 0) > 0]
        episode_payload = None
        if seasons:
            labels = [f"S{s['season_number']:02d}  ({s['episode_count']} eps) - {s.get('name','')}" for s in seasons]
            pick = pick_from_strings(labels, header="Season")
            if pick:
                snum = int(pick.split()[0][1:3])
                sdata = tmdb.tv_season(selected.id, snum)
                eps = sdata.get("episodes", [])
                poster_path = tvd.get("poster_path")
                backdrop_path = tvd.get("backdrop_path")
                poster_url = f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else None
                backdrop_url = f"https://image.tmdb.org/t/p/w300{backdrop_path}" if backdrop_path else None
                rows = []
                for e in eps:
                    enum = e.get("episode_number")
                    title = e.get("name", "")
                    text = f"S{snum:02d}E{enum:02d} - {title}"
                    payload = {
                        "id": selected.id,
                        "media_type": MediaType.tv.value,
                        "poster_url": poster_url,
                        "backdrop_url": backdrop_url,
                        "season": snum,
                        "episode": enum,
                        "details": (
                            f"Title: {selected.title}\n"
                            f"Episode: S{snum:02d}E{enum:02d} - {title}\n"
                            f"Air: {e.get('air_date','-')}\n\n"
                            f"Overview:\n{(e.get('overview') or '').strip()[:800]}"
                        ),
                    }
                    rows.append({"text": text, "payload": payload})
                ep_sel = pick_with_preview(rows, header="Episode")
                if ep_sel:
                    episode_payload = {"season": snum, "episode": ep_sel.get("episode")}
        # Decide method
        last_method = None
        for it in hist.summarize(limit=300):
            if it.get("media_type") == MediaType.tv.value and int(it.get("id")) == int(selected.id) and it.get("last_method"):
                last_method = it.get("last_method")
                break
        action = _pick_action()
        if not action or action == "skip":
            print("Skipped.")
            return 0
        if action == "play_vidsrc":
            return _play_with_vidsrc(cfg, hist, tmdb_id=selected.id, media_type_val=MediaType.tv.value, episode_payload=episode_payload, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
        if action == "play_torrentio":
            return _play_with_torrentio(cfg, hist, tmdb, tmdb_id=selected.id, media_type_val=MediaType.tv.value, episode_payload=episode_payload, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
        if action == "download_vidsrc":
            return _download_with_vidsrc(cfg, hist, tmdb_id=selected.id, media_type_val=MediaType.tv.value, episode_payload=episode_payload, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
        if action == "download_torrentio":
            return _download_with_torrentio(cfg, hist, tmdb, tmdb_id=selected.id, media_type_val=MediaType.tv.value, episode_payload=episode_payload, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
        return 0


def cmd_torrentio(media_type: str, tmdb_id: int, season: Optional[int], episode: Optional[int], json_out: bool, first_only: bool, timeout: int) -> int:
    mt = media_type.lower().strip()
    if mt not in {"movie", "tv"}:
        print("media_type must be 'movie' or 'tv'.")
        return 2
    if mt == "tv" and (not season or not episode):
        print("For tv, --season and --episode are required.")
        return 2
    cfg = ConfigManager().load()
    tmdb = TMDBClient(cfg.tmdb_api_key)
    try:
        if mt == "movie":
            imdb_id = tmdb.movie_external_ids(tmdb_id).get("imdb_id")
        else:
            imdb_id = tmdb.tv_external_ids(tmdb_id).get("imdb_id")
    except Exception as e:
        print(f"Failed to fetch external IDs: {e}")
        return 1
    if not imdb_id:
        print("No IMDb ID found for item.")
        return 1
    try:
        if mt == "movie":
            streams = torrentio_get_streams("movie", imdb_id, timeout=timeout)
        else:
            streams = torrentio_get_streams("tv", imdb_id, season=season, episode=episode, timeout=timeout)
    except Exception as e:
        print(f"Failed to fetch Torrentio streams: {e}")
        return 1
    if not streams:
        print("No Torrentio streams found.")
        return 0
    if json_out:
        out = []
        for s in streams:
            dn = s.behaviorHints.get("filename") or s.title
            magnet = torrentio_build_magnet(s.infoHash, display_name=dn, sources=s.sources)
            out.append({
                "name": s.name,
                "title": s.title,
                "infoHash": s.infoHash,
                "fileIdx": s.fileIdx,
                "behaviorHints": s.behaviorHints,
                "magnet": magnet,
            })
        if first_only:
            print(json.dumps(out[0], ensure_ascii=False))
        else:
            print(json.dumps(out, ensure_ascii=False))
        return 0
    # Interactive pick and launch
    labels = [s.display() for s in streams]
    pick = pick_from_strings(labels, header="Torrentio Stream")
    if not pick:
        print("Nothing selected.")
        return 0
    try:
        idx = labels.index(pick)
    except ValueError:
        idx = 0
    chosen: TorrentioStream = streams[idx]
    dn = chosen.behaviorHints.get("filename") or chosen.title
    magnet = torrentio_build_magnet(chosen.infoHash, display_name=dn, sources=chosen.sources)
    player = cfg.player if shutil.which(cfg.player) else ("mpv" if shutil.which("mpv") else ("vlc" if shutil.which("vlc") else None))
    if not player:
        print("No supported player (mpv/vlc) found on PATH.")
        print(f"Magnet: {magnet}")
        return 0
    if not torrentio_has_webtorrent():
        print("webtorrent-cli not found on PATH. Install with: npm i -g webtorrent-cli")
        print(f"Magnet: {magnet}")
        return 0
    print(f"Launching webtorrent -> {player} : {dn or chosen.infoHash[:8]}")
    try:
        torrentio_launch(
            magnet,
            player,
            file_idx=chosen.fileIdx,
            interactive=(chosen.fileIdx is None),
            playlist=False,
            out_dir=getattr(cfg, "webtorrent_tmp_dir", None),
        )
    except Exception as e:
        print(f"Failed to launch webtorrent: {e}")
    return 0

def cmd_vidsrc(media_type: str, tmdb_id: int, season: Optional[int], episode: Optional[int], json_out: bool, first_only: bool, max_hosts: int, timeout: int) -> int:
    mt = media_type.lower().strip()
    if mt not in {"movie", "tv"}:
        print("media_type must be 'movie' or 'tv'.")
        return 2
    if mt == "tv" and (not season or not episode):
        print("For tv, --season and --episode are required.")
        return 2
    items = scrape_vidsrc(mt, tmdb_id, season=season, episode=episode, max_hosts=max_hosts, timeout=timeout)
    if not items:
        print("No streams found.")
        return 0
    if json_out:
        out = [
            {
                "url": it.url,
                "kind": it.kind,
                "server_hash": it.server_hash,
                "rcp_host": it.rcp_host,
                "nested_url": it.nested_url,
            }
            for it in items
        ]
        if first_only:
            print(json.dumps(out[0], ensure_ascii=False))
        else:
            print(json.dumps(out, ensure_ascii=False))
        return 0
    # Plain text output
    printed = 0
    for it in items:
        print(f"[{it.kind}] {it.url}")
        printed += 1
        if first_only:
            break
    return 0


def cmd_search(query: Optional[str], no_preview: bool = False) -> int:
    cfg = ConfigManager().load()
    tmdb = TMDBClient(cfg.tmdb_api_key)
    hist = History()

    if not query:
        try:
            query = input("Search query: ").strip()
        except KeyboardInterrupt:
            return 1
    if not query:
        print("No query provided.")
        return 1

    print(f"Searching TMDB for: {query} ...", file=sys.stderr)
    items = tmdb.search_multi(query)
    if not items:
        print("No results.")
        return 0

    selected = run_fzf(items, preview=(cfg.image_preview and not no_preview))
    if not selected:
        print("Nothing selected.")
        return 0

    media_type_val = selected.media_type.value if hasattr(selected.media_type, "value") else str(selected.media_type)

    # If TV, drill down to season/episode
    episode_payload = None
    if media_type_val == MediaType.tv.value:
        tvd = tmdb.tv_details(selected.id)
        seasons = [s for s in tvd.get("seasons", []) if s.get("season_number", 0) > 0 and s.get("episode_count", 0) > 0]
        if seasons:
            labels = [f"S{s['season_number']:02d}  ({s['episode_count']} eps) - {s.get('name','')}" for s in seasons]
            pick = pick_from_strings(labels, header="Season")
            if pick:
                snum = int(pick.split()[0][1:3])
                sdata = tmdb.tv_season(selected.id, snum)
                eps = sdata.get("episodes", [])
                # Build episode rows with preview payload
                poster_path = tvd.get("poster_path")
                backdrop_path = tvd.get("backdrop_path")
                poster_url = f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else None
                backdrop_url = f"https://image.tmdb.org/t/p/w300{backdrop_path}" if backdrop_path else None
                rows = []
                for e in eps:
                    enum = e.get("episode_number")
                    title = e.get("name", "")
                    text = f"S{snum:02d}E{enum:02d} - {title}"
                    payload = {
                        "id": selected.id,
                        "media_type": MediaType.tv.value,
                        "poster_url": poster_url,
                        "backdrop_url": backdrop_url,
                        "season": snum,
                        "episode": enum,
                        # Lightweight details to show immediately; preview builds richer panel
                        "details": (
                            f"Title: {selected.title}\n"
                            f"Episode: S{snum:02d}E{enum:02d} - {title}\n"
                            f"Air: {e.get('air_date','-')}\n\n"
                            f"Overview:\n{(e.get('overview') or '').strip()[:800]}"
                        ),
                    }
                    rows.append({"text": text, "payload": payload})
                ep_sel = pick_with_preview(rows, header="Episode")
                if ep_sel:
                    enum = ep_sel.get("episode")
                    e = next((x for x in eps if x.get('episode_number') == enum), None)
                    if e:
                        episode_payload = {
                            "season": snum,
                            "episode": enum,
                            "episode_name": e.get("name"),
                            "air_date": e.get("air_date"),
                            "overview": e.get("overview"),
                        }

    # Persist selection to history (with episode when present)
    # Persist selection to history (with poster/backdrop for previews)
    hist.add(
        {
            "id": selected.id,
            "media_type": media_type_val,
            "title": selected.title,
            "release_year": selected.release_year,
            "vote_average": selected.vote_average,
            "poster_url": getattr(selected, "poster_url", None),
            "backdrop_url": getattr(selected, "backdrop_url", None),
            "source": "tmdb_search",
            "episode": episode_payload,
        }
    )

    output = {
        "id": selected.id,
        "media_type": media_type_val,
        "title": selected.title,
        "episode": episode_payload,
    }
    print(json.dumps(output, ensure_ascii=False))
    print("Saved to history.")

    # Action selection: play or download via VidSrc/Torrentio
    action = _pick_action()
    if not action or action == "skip":
        print("Skipped.")
        return 0
    if action == "play_vidsrc":
        return _play_with_vidsrc(cfg, hist, tmdb_id=selected.id, media_type_val=media_type_val, episode_payload=episode_payload, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
    if action == "play_torrentio":
        return _play_with_torrentio(cfg, hist, tmdb, tmdb_id=selected.id, media_type_val=media_type_val, episode_payload=episode_payload, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
    if action == "download_vidsrc":
        return _download_with_vidsrc(cfg, hist, tmdb_id=selected.id, media_type_val=media_type_val, episode_payload=episode_payload, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
    if action == "download_torrentio":
        return _download_with_torrentio(cfg, hist, tmdb, tmdb_id=selected.id, media_type_val=media_type_val, episode_payload=episode_payload, title=selected.title, poster_url=getattr(selected, "poster_url", None), backdrop_url=getattr(selected, "backdrop_url", None))
    return 0


def cmd_history(limit: int = 30) -> int:
    hist = History()
    rows = hist.list(limit=limit)
    if not rows:
        print("No history yet.")
        return 0
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(prog="cinecli", description="TMDB terminal browser with fzf/chafa")
    sub = p.add_subparsers(dest="cmd")

    p_setup = sub.add_parser("setup", help="Interactive configuration")

    p_search = sub.add_parser("search", help="Search movies/TV")
    p_search.add_argument("query", nargs="?", help="Search query")
    p_search.add_argument("--no-preview", action="store_true", help="Disable image preview")

    p_hist = sub.add_parser("history", help="Show watch/search history")
    p_hist.add_argument("--limit", type=int, default=30)

    p_dash = sub.add_parser("dashboard", help="Interactive dashboard: History and Popular lists")
    p_dash.add_argument("--no-preview", action="store_true", help="Disable image preview")

    p_vid = sub.add_parser("vidsrc", help="Scrape VidSrc links")
    p_vid.add_argument("media_type", choices=["movie", "tv"], help="Media type")
    p_vid.add_argument("tmdb_id", type=int, help="TMDB ID")
    p_vid.add_argument("-s", "--season", type=int, help="Season (TV)")
    p_vid.add_argument("-e", "--episode", type=int, help="Episode (TV)")
    p_vid.add_argument("--max-hosts", type=int, default=3)
    p_vid.add_argument("--timeout", type=int, default=8)
    p_vid.add_argument("--json", action="store_true", help="Output JSON")
    p_vid.add_argument("--first", action="store_true", help="Print only the first URL")

    p_tio = sub.add_parser("torrentio", help="Fetch Torrentio streams and play via webtorrent-cli")
    p_tio.add_argument("media_type", choices=["movie", "tv"], help="Media type")
    p_tio.add_argument("tmdb_id", type=int, help="TMDB ID")
    p_tio.add_argument("-s", "--season", type=int, help="Season (TV)")
    p_tio.add_argument("-e", "--episode", type=int, help="Episode (TV)")
    p_tio.add_argument("--timeout", type=int, default=12, help="HTTP timeout for Torrentio API")
    p_tio.add_argument("--json", action="store_true", help="Output JSON instead of launching")
    p_tio.add_argument("--first", action="store_true", help="Only return the top stream in JSON")

    args = p.parse_args(argv)

    if args.cmd == "setup":
        return cmd_setup()
    if args.cmd == "search":
        return cmd_search(args.query, no_preview=args.no_preview)
    if args.cmd == "history":
        return cmd_history(limit=args.limit)
    if args.cmd == "dashboard":
        return cmd_dashboard(no_preview=getattr(args, "no_preview", False))
    if args.cmd == "vidsrc":
        return cmd_vidsrc(
            args.media_type,
            args.tmdb_id,
            getattr(args, "season", None),
            getattr(args, "episode", None),
            getattr(args, "json", False),
            getattr(args, "first", False),
            getattr(args, "max_hosts", 3),
            getattr(args, "timeout", 8),
        )
    if args.cmd == "torrentio":
        return cmd_torrentio(
            args.media_type,
            args.tmdb_id,
            getattr(args, "season", None),
            getattr(args, "episode", None),
            getattr(args, "json", False),
            getattr(args, "first", False),
            getattr(args, "timeout", 12),
        )

    # Default to search if extra args provided (legacy behavior)
    if argv:
        return cmd_search(" ".join(argv))

    # No args: open dashboard by default
    return cmd_dashboard(no_preview=False)


if __name__ == "__main__":
    raise SystemExit(main())
