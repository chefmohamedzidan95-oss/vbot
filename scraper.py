"""
Backward compatibility layer for scraper imports.
Re-exports QfilmProvider as QfilmScraper and VideoResult.
"""

from providers.base import VideoResult
from providers.qfilm import QfilmProvider as QfilmScraper

__all__ = ["VideoResult", "QfilmScraper"]
