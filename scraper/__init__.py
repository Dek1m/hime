"""Data models for search results."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SearchResult:
    """Single search result from Google."""

    url: str
    title: str
    snippet: str
    position: int
    query: str = ""
    cached_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "position": self.position,
            "query": self.query,
            "cached_at": self.cached_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SearchResult":
        """Create from dictionary."""
        return cls(
            url=data.get("url", ""),
            title=data.get("title", ""),
            snippet=data.get("snippet", ""),
            position=data.get("position", 0),
            query=data.get("query", ""),
            cached_at=data.get("cached_at", ""),
        )
