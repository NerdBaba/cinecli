from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from shutil import which
from subprocess import run
import textwrap
from typing import Any

import requests

from .config import CACHE_DIR
from .config import ConfigManager
from .tmdb import TMDBClient


IMG_SIZE = "w342"


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"{h}.jpg"


def _download(url: str, dest: Path) -> bool:
    """Download URL to dest if not present. Returns True if file exists after call."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return True
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception:
        return dest.exists() and dest.stat().st_size > 0


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    line = sys.argv[1]
    try:
        item = json.loads(line)
    except Exception:
        # Try base64 (urlsafe) decoding
        try:
            import base64
            item = json.loads(base64.urlsafe_b64decode(line.encode("ascii")).decode("utf-8"))
        except Exception:
            return 0

    # Determine preview dims first (needed for text formatting)
    try:
        cols_env = os.environ.get("FZF_PREVIEW_COLUMNS")
        lines_env = os.environ.get("FZF_PREVIEW_LINES")
        if cols_env and lines_env:
            cols = int(cols_env)
            lines = int(lines_env)
        else:
            # fallback to stty size
            import subprocess
            out = subprocess.check_output(["sh", "-c", "stty size </dev/tty"], stderr=subprocess.DEVNULL).decode().strip()
            parts = out.split()
            lines = int(parts[0]) if len(parts) >= 1 else 40
            cols = int(parts[1]) if len(parts) >= 2 else 80
    except Exception:
        cols, lines = 80, 40
    dim = f"{cols}x{lines}"

    poster_url = item.get("poster_url") or item.get("backdrop_url")
    # Build pretty info panel (cached)
    media_type = item.get("media_type")
    media_id = item.get("id")
    snum = item.get("season")
    enum = item.get("episode")

    cache_suffix = f"_{snum}x{enum}" if (snum and enum) else ""
    info_cache = CACHE_DIR / f"info_{media_type}_{media_id}{cache_suffix}.txt"
    if info_cache.exists() and info_cache.stat().st_size > 0:
        details = info_cache.read_text(encoding="utf-8")
    else:
        # Load TMDB details and format
        try:
            cfg = ConfigManager().load()
            tmdb = TMDBClient(cfg.tmdb_api_key)
            def rule_line(width: int) -> str:
                return "\033[2m" + ("─" * max(10, min(width, cols))) + "\033[0m\n"

            def kv(key: str, val: str) -> str:
                # right-pad spaces so values align visually; reserve 2 spaces after colon
                k = f"\033[1;35m{key}:\033[0m "
                # wrap values if too long
                avail = max(10, cols - len(key) - 3)
                wrapped = textwrap.wrap(val or "-", width=avail)
                if not wrapped:
                    wrapped = ["-"]
                first = k + wrapped[0]
                if len(wrapped) == 1:
                    return first + "\n"
                # indent following lines under the value start
                indent = " " * (len(key) + 2)
                return first + "\n" + "\n".join(indent + w for w in wrapped[1:]) + "\n"

            if media_type == "movie" and not (snum and enum):
                url = f"https://api.themoviedb.org/3/movie/{media_id}"
                r = tmdb.session.get(url, timeout=4)
                r.raise_for_status()
                d = r.json()
                title = d.get("title") or d.get("original_title") or "Unknown"
                rating = d.get("vote_average")
                votes = d.get("vote_count")
                runtime = d.get("runtime")
                genres = ", ".join([g.get("name") for g in d.get("genres", [])])
                status = d.get("status")
                release = d.get("release_date")
                overview = (d.get("overview") or "").strip()
                details = (
                    kv("Title", title)
                    + rule_line(cols)
                    + kv("Score", f"{rating or '-'}  \033[2m({votes or 0} votes)\033[0m")
                    + kv("Runtime", f"{runtime or '-'} min")
                    + kv("Genres", genres or "-")
                    + kv("Status", status or "-")
                    + kv("Release", release or "-")
                )
                if overview:
                    details += "\n" + rule_line(cols) + textwrap.fill(overview, width=cols) + "\n"
            elif media_type == "tv" and (snum and enum):
                url = f"https://api.themoviedb.org/3/tv/{media_id}/season/{snum}/episode/{enum}"
                r = tmdb.session.get(url, timeout=4)
                r.raise_for_status()
                e = r.json()
                # Also grab show title for header
                sd = tmdb.session.get(f"https://api.themoviedb.org/3/tv/{media_id}", timeout=4)
                show_title = (sd.json().get("name") if sd.ok else None) or item.get("title") or "Unknown"
                etitle = e.get("name") or ""
                air = e.get("air_date")
                runtime = e.get("runtime")
                rating = e.get("vote_average")
                overview = (e.get("overview") or "").strip()
                details = (
                    kv("Title", show_title)
                    + kv("Episode", f"S{snum:02d}E{enum:02d} - {etitle}")
                    + rule_line(cols)
                    + kv("Score", f"{rating or '-'}")
                    + kv("Air", air or "-")
                    + kv("Runtime", f"{runtime or '-'} min")
                )
                if overview:
                    details += "\n" + rule_line(cols) + textwrap.fill(overview, width=cols) + "\n"
            else:
                url = f"https://api.themoviedb.org/3/tv/{media_id}"
                r = tmdb.session.get(url, timeout=4)
                r.raise_for_status()
                d = r.json()
                title = d.get("name") or d.get("original_name") or "Unknown"
                rating = d.get("vote_average")
                votes = d.get("vote_count")
                status = d.get("status")
                nseasons = d.get("number_of_seasons")
                neps = d.get("number_of_episodes")
                epmins = None
                ert = d.get("episode_run_time") or []
                if ert:
                    epmins = ert[0]
                genres = ", ".join([g.get("name") for g in d.get("genres", [])])
                overview = (d.get("overview") or "").strip()
                details = (
                    kv("Title", title)
                    + rule_line(cols)
                    + kv("Score", f"{rating or '-'}  \033[2m({votes or 0} votes)\033[0m")
                    + kv("Seasons", f"{nseasons or '-'}")
                    + kv("Episodes", f"{neps or '-'}")
                    + kv("Ep Length", f"{epmins or '-'} min")
                    + kv("Genres", genres or "-")
                    + kv("Status", status or "-")
                )
                if overview:
                    details += "\n" + rule_line(cols) + textwrap.fill(overview, width=cols) + "\n"
        except Exception:
            details = item.get("details") or ""
        try:
            info_cache.write_text(details, encoding="utf-8")
        except Exception:
            pass

    if not poster_url:
        print("(no poster)")
        return 0

    # Cache the image and render from file
    img_path = _cache_path(poster_url)
    have_file = _download(poster_url, img_path)
    if not have_file:
        print("🖼️  Loading image...")
        # still show details while loading
        if details:
            print()
            print(details)
        return 0

    # Prefer kitty/wezterm icat placement if available
    icat = which("icat") or which("kitten") or which("kitty")
    if icat is not None:
        try:
            base = os.path.basename(icat)
            # Compute place like viu
            is_ghostty = bool(os.environ.get("GHOSTTY_BIN_DIR"))
            is_kitty = bool(os.environ.get("KITTY_WINDOW_ID"))
            # When preview is at terminal bottom and not kitty, shrink height by 1 to avoid overflow
            try:
                preview_top = int(os.environ.get("FZF_PREVIEW_TOP", "0"))
                term_rows = 0
                try:
                    import subprocess as _sp
                    out = _sp.check_output(["sh", "-lc", "stty size </dev/tty"], stderr=_sp.DEVNULL).decode().strip()
                    term_rows = int(out.split()[0]) if out else 0
                except Exception:
                    term_rows = 0
                if (not is_kitty) and (preview_top + lines == term_rows) and lines > 1:
                    lines_adj = lines - 1
                else:
                    lines_adj = lines
            except Exception:
                lines_adj = lines
            # Width rules (match viu): Ghostty uses width-1, others use full width
            if is_ghostty:
                w = max(1, cols - 1)
            else:
                w = max(1, cols)
            h = max(1, lines_adj)
            place = f"{w}x{h}@0x0"
            # Default: only use placeholder path in Kitty; allow override via env
            env_no_ph = str(os.environ.get("CINE_NO_PLACEHOLDER", "")).lower()
            if env_no_ph in {"1", "true", "yes", "on"}:
                use_placeholder = False
            elif env_no_ph in {"0", "false", "no", "off"}:
                use_placeholder = True if is_kitty else False
            else:
                use_placeholder = is_kitty

            # Non-placeholder path (explicit spacing) for terminals that misrender placeholders
            if not use_placeholder:
                chafa_bin = which("chafa")
                if chafa_bin:
                    from subprocess import run as _run
                    _run([chafa_bin, "-s", dim, str(img_path)], check=False)
                    print()
                    if details:
                        print(details)
                    return 0
                else:
                    # Fallback: draw with icat once and move cursor below image using ANSI CUD
                    if base == "kitten":
                        cmd_str = f'kitten icat --clear --transfer-mode=memory --stdin=no --place="{place}" "{img_path}"'
                    elif base == "icat":
                        cmd_str = f'icat --clear --transfer-mode=memory --stdin=no --place="{place}" "{img_path}"'
                    else:
                        cmd_str = f'kitty icat --clear --transfer-mode=memory --stdin=no --place="{place}" "{img_path}"'
                    from subprocess import run as _run
                    _run(["sh", "-lc", cmd_str], check=False)
                    try:
                        sys.stdout.write(f"\033[{h}B\n")
                    except Exception:
                        sys.stdout.write("\n")
                    sys.stdout.flush()
                    if details:
                        print(details)
                    return 0

            # Placeholder path that matches viu's sed pipeline and quoting exactly (Kitty)
            scale_flag = " --scale-up" if str(os.environ.get("CINE_SCALE_UP", "")).lower() in {"1","true","yes","on"} else ""
            if base == "kitten":
                cmd_str = f'kitten icat --clear --transfer-mode=memory --unicode-placeholder{scale_flag} --stdin=no --place="{place}" "{img_path}" | sed "\\$d" | sed "$(printf "\\$s/\\$/\\033[m/")"'
            elif base == "icat":
                cmd_str = f'icat --clear --transfer-mode=memory --unicode-placeholder{scale_flag} --stdin=no --place="{place}" "{img_path}" | sed "\\$d" | sed "$(printf "\\$s/\\$/\\033[m/")"'
            else:
                cmd_str = f'kitty icat --clear --transfer-mode=memory --unicode-placeholder{scale_flag} --stdin=no --place="{place}" "{img_path}" | sed "\\$d" | sed "$(printf "\\$s/\\$/\\033[m/")"'
            from subprocess import run as _run
            _run(["sh", "-lc", cmd_str], check=False)
            # Print one newline for spacing like viu's caller does
            print()
            if details:
                print(details)
            return 0
        except Exception:
            pass

    # Fallback to chafa with file input and size
    chafa = which("chafa")
    if chafa is not None:
        try:
            run([chafa, "-s", dim, str(img_path)], check=False)
            print()  # spacing like viu
            if details:
                print(details)
        except Exception:
            print("(chafa render failed)")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
