from __future__ import annotations
from typing import Optional

from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
from dateutil import parser as dateutil_parser
from loguru import logger


@dataclass
class RawArticle:
    url: str
    title: str
    published_at: Optional[datetime]
    summary_raw: Optional[str]


def parse_rss(feed_content: str | bytes, source_url: str) -> list[RawArticle]:
    """Parse RSS/Atom feed content and return a list of RawArticle."""
    feed = feedparser.parse(feed_content)

    if feed.bozo and not feed.entries:
        logger.warning("Bozo feed (malformed XML) from {}: {}", source_url, feed.bozo_exception)

    articles: list[RawArticle] = []
    for entry in feed.entries:
        url = _extract_url(entry)
        if not url:
            continue

        title = _clean(getattr(entry, "title", "") or "")
        if not title:
            continue

        published_at = _extract_date(entry)
        summary_raw = _extract_summary(entry)

        articles.append(
            RawArticle(
                url=url,
                title=title,
                published_at=published_at,
                summary_raw=summary_raw,
            )
        )

    return articles


def _extract_url(entry: feedparser.FeedParserDict) -> str | None:
    for attr in ("link", "id", "guid"):
        val = getattr(entry, attr, None)
        if val and val.startswith("http"):
            return val.strip()
    return None


def _extract_date(entry: feedparser.FeedParserDict) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                import time
                ts = time.mktime(val)
                return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
            except Exception:
                pass

    for attr in ("published", "updated", "created"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return dateutil_parser.parse(val).replace(tzinfo=None)
            except Exception:
                pass

    return None


def _extract_summary(entry: feedparser.FeedParserDict) -> str | None:
    for attr in ("summary", "description", "content"):
        val = getattr(entry, attr, None)
        if val:
            if isinstance(val, list):
                val = val[0].get("value", "") if val else ""
            text = _clean(val)
            if text:
                return text[:500]
    return None


def _clean(text: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
