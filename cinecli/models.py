from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class MediaType(str, Enum):
    movie = "movie"
    tv = "tv"


class MediaItem(BaseModel):
    id: int
    media_type: MediaType
    title: str
    overview: str = ""
    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None
    vote_average: Optional[float] = None
    release_year: Optional[int] = None
    seasons: Optional[int] = None
    episodes: Optional[int] = None

    @property
    def poster_url(self) -> Optional[str]:
        if not self.poster_path:
            return None
        # w342 is a good balance for terminal preview
        return f"https://image.tmdb.org/t/p/w342{self.poster_path}"

    @property
    def backdrop_url(self) -> Optional[str]:
        if not self.backdrop_path:
            return None
        return f"https://image.tmdb.org/t/p/w300{self.backdrop_path}"

    def display_title(self) -> str:
        yr = f" ({self.release_year})" if self.release_year else ""
        rating = f" ★{self.vote_average:.1f}" if self.vote_average is not None else ""
        prefix = "🎬" if self.media_type == MediaType.movie else "📺"
        return f"{prefix} {self.title}{yr}{rating} [id:{self.id}]"
