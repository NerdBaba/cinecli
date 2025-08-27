from __future__ import annotations

import json
import shutil
import subprocess
from typing import Iterable, Optional

from .models import MediaItem, MediaType
import base64
import sys


def ensure_binary(name: str) -> bool:
    return shutil.which(name) is not None


def to_fzf_line(item: MediaItem) -> str:
    type_label = "Movie" if str(item.media_type) == "MediaType.movie" or getattr(item.media_type, "value", str(item.media_type)) == "movie" else "TV"
    rating = f"{item.vote_average:.1f}" if item.vote_average is not None else "-"
    details = (
        f"Title: {item.title}\n"
        f"Type: {type_label}\n"
        f"Year: {item.release_year or '-'}\n"
        f"Rating: {rating}\n\n"
        f"Overview:\n{(item.overview or '').strip()[:1200]}"
    )
    payload = {
        "id": item.id,
        "media_type": getattr(item.media_type, "value", str(item.media_type)),
        # include raw paths so the selection can reconstruct full URLs later
        "poster_path": item.poster_path,
        "backdrop_path": item.backdrop_path,
        # keep convenience URLs for preview script callers that expect them
        "poster_url": item.poster_url,
        "backdrop_url": getattr(item, "backdrop_url", None),
        "details": details,
        "title": item.title,
        "overview": item.overview,
        "vote_average": item.vote_average,
        "release_year": item.release_year,
    }
    # Two fields separated by tab: visible text and base64 JSON payload
    b64 = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"{item.display_title()}\t{b64}"


def run_fzf(items: Iterable[MediaItem], preview: bool = True) -> Optional[MediaItem]:
    lines = [to_fzf_line(it) for it in items]
    if not lines:
        return None

    if not ensure_binary("fzf"):
        # Fallback: just print list and return first
        print("fzf not found; returning first result.")
        sel = lines[0]
        json_part = sel.split("\t", 1)[1]
        try:
            meta = json.loads(json_part)
        except Exception:
            import base64 as _b64
            try:
                meta = json.loads(_b64.urlsafe_b64decode(json_part.encode("ascii")).decode("utf-8"))
            except Exception:
                meta = {}
        return MediaItem(
            id=meta.get("id", 0),
            media_type=meta.get("media_type", MediaType.movie.value),
            title=meta.get("title", sel.split("\t", 1)[0]),
            overview=meta.get("overview", ""),
            vote_average=meta.get("vote_average"),
            poster_path=meta.get("poster_path"),
            backdrop_path=meta.get("backdrop_path"),
            release_year=meta.get("release_year"),
        )

    cmd = [
        "fzf",
        "--ansi",
        "--with-nth=1",
        "--delimiter=\t",
        "--bind=change:first",
        # Re-render image when preview is moved to top via Home, and on resize
        "--bind=home:preview-top+refresh-preview,resize:refresh-preview",
        "--prompt=CineCLI> ",
    ]
    if preview:
        cmd += [
            "--preview",
            f"{sys.executable} -m cinecli.preview {{2}}",
            "--preview-window=right:70%:wrap",
        ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin and proc.stdout
    proc.stdin.write("\n".join(lines))
    proc.stdin.close()
    out = proc.stdout.read()
    proc.wait()

    if not out:
        return None

    selected = out.strip().split("\n")[-1]
    if "\t" not in selected:
        return None
    title_part, json_part = selected.split("\t", 1)
    try:
        meta = json.loads(json_part)
    except Exception:
        try:
            meta = json.loads(base64.urlsafe_b64decode(json_part.encode("ascii")).decode("utf-8"))
        except Exception:
            meta = {}

    return MediaItem(
        id=meta["id"],
        media_type=meta["media_type"],
        title=meta.get("title", title_part),
        overview=meta.get("overview", ""),
        vote_average=meta.get("vote_average"),
        poster_path=meta.get("poster_path"),
        backdrop_path=meta.get("backdrop_path"),
        release_year=meta.get("release_year"),
    )


def pick_from_strings(options: list[str], header: str = "Select") -> Optional[str]:
    if not options:
        return None
    if not ensure_binary("fzf"):
        return options[0]
    cmd = [
        "fzf",
        "--prompt=" + header + "> ",
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdin and proc.stdout
    proc.stdin.write("\n".join(options))
    proc.stdin.close()
    out = proc.stdout.read()
    proc.wait()
    return out.strip() if out else None


def pick_with_preview(rows: list[dict], header: str = "Select") -> Optional[dict]:
    """
    rows: [{"text": str, "payload": dict}]
    Returns selected payload dict or None.
    """
    if not rows:
        return None
    if not ensure_binary("fzf"):
        return rows[0]["payload"]
    lines = []
    for r in rows:
        b64 = base64.urlsafe_b64encode(json.dumps(r["payload"], ensure_ascii=False).encode("utf-8")).decode("ascii")
        lines.append(f"{r['text']}\t{b64}")

    cmd = [
        "fzf",
        "--prompt=" + header + "> ",
        "--with-nth=1",
        "--delimiter=\t",
        "--ansi",
        "--bind=change:first",
        # Same bindings for episode picker preview
        "--bind=home:preview-top+refresh-preview,resize:refresh-preview",
        "--preview",
        f"{sys.executable} -m cinecli.preview {{2}}",
        "--preview-window=right:70%:wrap",
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdin and proc.stdout
    proc.stdin.write("\n".join(lines))
    proc.stdin.close()
    out = proc.stdout.read()
    proc.wait()
    if not out:
        return None
    sel = out.strip().split("\n")[-1]
    if "\t" not in sel:
        return None
    _, payload_b64 = sel.split("\t", 1)
    try:
        return json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
