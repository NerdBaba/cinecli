from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List

import requests

from .models import MediaItem, MediaType


class TMDBClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base = "https://api.themoviedb.org/3"
        self.session = requests.Session()
        self.session.params = {"api_key": self.api_key}

    def search_multi(self, query: str, language: str = "en-US", include_adult: bool = False) -> List[MediaItem]:
        url = f"{self.base}/search/multi"
        params = {"query": query, "language": language, "include_adult": str(include_adult).lower()}
        r = self.session.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        items: List[MediaItem] = []
        for it in data.get("results", []):
            mtype = it.get("media_type")
            if mtype not in {"movie", "tv"}:
                continue
            title = it.get("title") or it.get("name") or "Unknown"
            date = it.get("release_date") or it.get("first_air_date")
            year = None
            if date:
                try:
                    year = int(date.split("-")[0])
                except Exception:
                    year = None
            items.append(
                MediaItem(
                    id=it.get("id"),
                    media_type=MediaType(mtype),
                    title=title,
                    overview=it.get("overview") or "",
                    poster_path=it.get("poster_path"),
                    backdrop_path=it.get("backdrop_path"),
                    vote_average=it.get("vote_average"),
                    release_year=year,
                )
            )
        return items

    # --- TV helpers ---
    def tv_details(self, tv_id: int, language: str = "en-US") -> Dict[str, Any]:
        url = f"{self.base}/tv/{tv_id}"
        r = self.session.get(url, params={"language": language}, timeout=20)
        r.raise_for_status()
        return r.json()

    def tv_season(self, tv_id: int, season_number: int, language: str = "en-US") -> Dict[str, Any]:
        url = f"{self.base}/tv/{tv_id}/season/{season_number}"
        r = self.session.get(url, params={"language": language}, timeout=20)
        r.raise_for_status()
        return r.json()

    # --- External IDs ---
    def movie_external_ids(self, movie_id: int) -> Dict[str, Any]:
        url = f"{self.base}/movie/{movie_id}/external_ids"
        r = self.session.get(url, timeout=20)
        r.raise_for_status()
        return r.json()

    def tv_external_ids(self, tv_id: int) -> Dict[str, Any]:
        url = f"{self.base}/tv/{tv_id}/external_ids"
        r = self.session.get(url, timeout=20)
        r.raise_for_status()
        return r.json()

    # --- Popular lists ---
    def movie_popular(self, page: int = 1, language: str = "en-US") -> List[MediaItem]:
        url = f"{self.base}/movie/popular"
        r = self.session.get(url, params={"page": page, "language": language}, timeout=20)
        r.raise_for_status()
        data = r.json()
        items: List[MediaItem] = []
        for it in data.get("results", []):
            title = it.get("title") or it.get("original_title") or "Unknown"
            date = it.get("release_date")
            year = None
            if date:
                try:
                    year = int(date.split("-")[0])
                except Exception:
                    year = None
            items.append(
                MediaItem(
                    id=it.get("id"),
                    media_type=MediaType.movie,
                    title=title,
                    overview=it.get("overview") or "",
                    poster_path=it.get("poster_path"),
                    backdrop_path=it.get("backdrop_path"),
                    vote_average=it.get("vote_average"),
                    release_year=year,
                )
            )
        return items

    def tv_popular(self, page: int = 1, language: str = "en-US") -> List[MediaItem]:
        url = f"{self.base}/tv/popular"
        r = self.session.get(url, params={"page": page, "language": language}, timeout=20)
        r.raise_for_status()
        data = r.json()
        items: List[MediaItem] = []
        for it in data.get("results", []):
            title = it.get("name") or it.get("original_name") or "Unknown"
            date = it.get("first_air_date")
            year = None
            if date:
                try:
                    year = int(date.split("-")[0])
                except Exception:
                    year = None
            items.append(
                MediaItem(
                    id=it.get("id"),
                    media_type=MediaType.tv,
                    title=title,
                    overview=it.get("overview") or "",
                    poster_path=it.get("poster_path"),
                    backdrop_path=it.get("backdrop_path"),
                    vote_average=it.get("vote_average"),
                    release_year=year,
                )
            )
        return items
