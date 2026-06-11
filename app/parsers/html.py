from __future__ import annotations
from typing import Optional

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlparse

from dateutil import parser as dateutil_parser
from loguru import logger
from selectolax.parser import HTMLParser


@dataclass
class RawArticle:
    url: str
    title: str
    published_at: Optional[datetime]
    summary_raw: Optional[str]


def parse_html(
    html_content: str,
    base_url: str,
    selector: str,
    title_sel: Optional[str] = None,
    link_sel: Optional[str] = None,
    date_sel: Optional[str] = None,
    summary_sel: Optional[str] = None,
) -> list[RawArticle]:
    """Parse HTML page and extract articles using CSS selectors."""
    tree = HTMLParser(html_content)
    articles: list[RawArticle] = []

    nodes = tree.css(selector)
    if not nodes:
        logger.warning("Selector '{}' matched 0 nodes on {}", selector, base_url)
        return articles

    for node in nodes:
        title, url = _extract_title_and_url(node, base_url, title_sel, link_sel)
        if not title or not url:
            continue

        published_at = _extract_date(node, date_sel)
        summary_raw = _extract_summary(node, summary_sel)

        articles.append(
            RawArticle(
                url=url,
                title=title,
                published_at=published_at,
                summary_raw=summary_raw,
            )
        )

    return articles


def _extract_title_and_url(
    node,
    base_url: str,
    title_sel: Optional[str],
    link_sel: Optional[str],
) -> tuple[str | None, str | None]:
    title: Optional[str] = None
    url: Optional[str] = None

    # Try dedicated title selector first
    if title_sel:
        for sel in _split_sel(title_sel):
            t = node.css_first(sel)
            if t:
                title = _text(t)
                break

    # Try dedicated link selector
    if link_sel:
        for sel in _split_sel(link_sel):
            a = node.css_first(sel)
            if a:
                href = a.attributes.get("href", "")
                if href:
                    url = _absolute(href, base_url)
                if not title:
                    title = _text(a)
                break

    # Fallback: any <a> in the node
    if not url:
        a = node.css_first("a[href]")
        if a:
            href = a.attributes.get("href", "")
            if href:
                url = _absolute(href, base_url)
            if not title:
                title = _text(a)

    # Fallback: any heading in node
    if not title:
        for sel in ("h1", "h2", "h3", "h4"):
            h = node.css_first(sel)
            if h:
                title = _text(h)
                break

    if title:
        title = title[:500]

    return title or None, url or None


def _extract_date(node, date_sel: Optional[str]) -> datetime | None:
    candidates = []

    if date_sel:
        for sel in _split_sel(date_sel):
            d = node.css_first(sel)
            if d:
                # Try datetime attribute first
                dt_attr = d.attributes.get("datetime") or d.attributes.get("content")
                if dt_attr:
                    candidates.append(dt_attr)
                candidates.append(_text(d))

    # Also try <time> and common date classes regardless
    for sel in ("time[datetime]", "time", "[class*=date]", "[class*=Date]"):
        d = node.css_first(sel)
        if d:
            dt_attr = d.attributes.get("datetime") or d.attributes.get("content")
            if dt_attr:
                candidates.append(dt_attr)
            candidates.append(_text(d))

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return dateutil_parser.parse(candidate, fuzzy=True).replace(tzinfo=None)
        except Exception:
            continue

    return None


def _extract_summary(node, summary_sel: Optional[str]) -> str | None:
    if summary_sel:
        for sel in _split_sel(summary_sel):
            s = node.css_first(sel)
            if s:
                text = _text(s)
                if text:
                    return text[:500]

    for sel in ("p", ".excerpt", ".description", ".summary"):
        s = node.css_first(sel)
        if s:
            text = _text(s)
            if text:
                return text[:500]

    return None


def _split_sel(sel: str) -> list[str]:
    return [s.strip() for s in sel.split(",") if s.strip()]


def _text(node) -> str:
    import re
    raw = node.text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", raw).strip()


def _absolute(href: str, base_url: str) -> str:
    href = href.strip()
    if href.startswith("http"):
        return href
    return urljoin(base_url, href)
