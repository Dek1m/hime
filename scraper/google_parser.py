"""Google search results parser."""

import logging
import re
from urllib.parse import urlparse, parse_qs, unquote

from selectolax.parser import HTMLParser

from hime.scraper import SearchResult

logger = logging.getLogger(__name__)

# CSS selectors for Google results (fallback chain)
_RESULT_SELECTORS = ["div.g", "div.tF2Cxc", "div[data-hveid]"]
_TITLE_SELECTORS = ["h3", "div.VXB6be", "div[data-sncf]"]
_LINK_SELECTORS = ["a[href]", "a"]
_SNIPPET_SELECTORS = [
    "div.VwiC3b",
    "div[data-sncf]",
    "span.aCOpRe",
    "div.s3v9rd",
]

# CAPTCHA / block indicators
_CAPTCHA_MARKERS = ["unusual traffic", "captcha", "sorry/index", "sorry/message"]


def _extract_text(node, selectors: list[str]) -> str:
    """Try multiple selectors, return first non-empty text."""
    for sel in selectors:
        child = node.css_first(sel)
        if child and child.text(strip=True):
            return child.text(strip=True)
    return ""


def _extract_url(node, selectors: list[str]) -> str:
    """Try multiple selectors, return first href."""
    for sel in selectors:
        child = node.css_first(sel)
        if child:
            href = child.attributes.get("href", "")
            if href and href.startswith("http"):
                return _clean_url(href)
    return ""


def _clean_url(url: str) -> str:
    """Extract real URL from Google redirect wrapper."""
    if "/url?" in url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "q" in qs:
            return qs["q"][0]
        if "url" in qs:
            return qs["url"][0]
    return url.split("&sa=")[0] if "&sa=" in url else url


def _is_captcha(html: str) -> bool:
    """Check if response is a CAPTCHA page."""
    lower = html.lower()
    return any(marker in lower for marker in _CAPTCHA_MARKERS)


class GoogleParser:
    """Parse Google search results HTML."""

    def parse(self, html: str, query: str = "") -> list[SearchResult]:
        """
        Parse Google search HTML into structured results.

        Returns list of SearchResult or empty list on CAPTCHA/block.
        """
        if not html or not html.strip():
            return []

        if _is_captcha(html):
            logger.warning("CAPTCHA/block detected, skipping parse")
            return []

        tree = HTMLParser(html)
        results: list[SearchResult] = []
        position = 0

        for selector in _RESULT_SELECTORS:
            items = tree.css(selector)
            if items:
                break
        else:
            items = []

        for item in items:
            title = _extract_text(item, _TITLE_SELECTORS)
            url = _extract_url(item, _LINK_SELECTORS)
            snippet = _extract_text(item, _SNIPPET_SELECTORS)

            if not url or not title:
                continue

            # Skip Google internal links
            parsed = urlparse(url)
            if parsed.netloc and "google" in parsed.netloc:
                continue

            position += 1
            results.append(
                SearchResult(
                    url=url,
                    title=title,
                    snippet=snippet,
                    position=position,
                    query=query,
                )
            )

        logger.info("Parsed %d results for query='%s'", len(results), query)
        return results
