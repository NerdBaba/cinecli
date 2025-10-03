from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Optional

from pydantic import BaseModel, Field, ValidationError


CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "cinecli"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "cinecli"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "cinecli"


class Settings(BaseModel):
    tmdb_api_key: str = Field(..., min_length=10)
    player: str = Field("mpv", pattern=r"^(mpv|vlc|clapper)$")
    image_preview: bool = True
    history_path: str = str(DATA_DIR / "history.jsonl")
    webtorrent_tmp_dir: str = str(CACHE_DIR / "webtorrent")
    # Optional TorBox API key; if empty, TorBox features are hidden
    torbox_api_key: str = ""
    # Optional: Streamthru and Comet manifest base URLs (must end with /manifest.json)
    streamthru_manifest_url: str = ""
    comet_manifest_url: str = ""


class ConfigManager:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or (CONFIG_DIR / "config.json")
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def load(self) -> Settings:
        # ENV overrides
        env_key = os.environ.get("TMDB_API_KEY")
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        else:
            raw = {}
        if env_key:
            raw["tmdb_api_key"] = env_key
        try:
            return Settings(**raw)
        except ValidationError:
            return self.interactive_setup()

    def save(self, settings: Settings) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(settings.model_dump(), f, indent=2)

    def interactive_setup(self) -> Settings:
        print("-- CineCLI initial setup --")
        while True:
            api_key = input("Enter TMDB API key: ").strip()
            if len(api_key) >= 10:
                break
            print("Invalid key, try again.")
        player = "mpv"
        pref = input("Preferred player (mpv/vlc/clapper) [mpv]: ").strip().lower()
        if pref in {"mpv", "vlc", "clapper"}:
            player = pref
        has_chafa = which("chafa") is not None
        image_preview = has_chafa
        if has_chafa:
            yn = input("Enable poster previews with chafa? [Y/n]: ").strip().lower()
            image_preview = yn != "n"
        else:
            print("chafa not found on PATH; previews will be disabled.")
            image_preview = False
        # Configure webtorrent temp directory
        default_tmp = str(CACHE_DIR / "webtorrent")
        tmp_in = input(f"Temp directory for webtorrent-cli [{default_tmp}]: ").strip()
        webtorrent_tmp_dir = tmp_in or default_tmp
        try:
            Path(webtorrent_tmp_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            print(f"Warning: could not create directory: {webtorrent_tmp_dir}")
        # Optional providers gated behind TorBox key
        torbox_api_key = input("TorBox API key (optional, press Enter to skip): ").strip()
        streamthru_manifest_url = input("Streamthru manifest URL (optional, press Enter to skip): ").strip()
        comet_manifest_url = input("Comet manifest URL (optional, press Enter to skip): ").strip()
        settings = Settings(
            tmdb_api_key=api_key,
            player=player,
            image_preview=image_preview,
            webtorrent_tmp_dir=webtorrent_tmp_dir,
            torbox_api_key=torbox_api_key,
            streamthru_manifest_url=streamthru_manifest_url,
            comet_manifest_url=comet_manifest_url,
        )
        self.save(settings)
        print(f"Saved config to {self.path}")
        return settings
