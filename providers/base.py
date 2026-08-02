from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class VideoResult:
    vid: str
    title: str
    watch_url: str
    thumb_url: str
    duration: str = ""
    labels: List[str] = field(default_factory=list)
    description: str = ""
    categories: List[str] = field(default_factory=list)
    views: int = 0
    quality: str = ""
    is_series: bool = False
    direct_links: List[Dict[str, str]] = field(default_factory=list)
    provider_id: str = ""


@dataclass
class Category:
    id: str
    name: str
    icon: str = "📂"


class BaseProvider(ABC):
    """
    Abstract base class for movie and series content providers.
    Extend this class to add new websites/sources to FlixMix Bot.
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique string ID for the provider (e.g. 'qfilm')."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable display name for the provider."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Brief description of the provider source."""
        pass

    @abstractmethod
    def get_categories(self) -> List[Category]:
        """Return list of categories/genres available in this provider."""
        pass

    @abstractmethod
    def search(self, query: str, page: int = 1) -> List[VideoResult]:
        """Search for movies/series by query string with pagination."""
        pass

    @abstractmethod
    def get_by_category(self, category_id: str, page: int = 1) -> List[VideoResult]:
        """Get list of movies/series in a specific category with pagination."""
        pass

    @abstractmethod
    def get_video_details(self, vid: str, extra: Optional[dict] = None) -> VideoResult:
        """Fetch full details and direct links for a specific movie or series video ID."""
        pass

    @abstractmethod
    def get_series_episodes(self, series_identifier: str) -> List[VideoResult]:
        """Fetch list of episodes for a series."""
        pass

    @abstractmethod
    def get_web_app_url(self, video: VideoResult) -> str:
        """Return HTTPS Web App URL for playback inside Telegram WebApp button."""
        pass
