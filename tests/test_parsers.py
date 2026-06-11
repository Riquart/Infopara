"""Tests des parsers RSS et HTML sur fixtures offline."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.parsers.rss import parse_rss
from app.parsers.html import parse_html

FIXTURES = Path(__file__).parent / "fixtures"


# ──────────────────────────────────────────────────────────────
# RSS parser
# ──────────────────────────────────────────────────────────────

def _rss_articles():
    content = (FIXTURES / "sample_rss.xml").read_bytes()
    return parse_rss(content, "https://www.ameli.fr/infirmier/actualites/rss")


def test_rss_returns_list():
    articles = _rss_articles()
    assert isinstance(articles, list)


def test_rss_correct_count():
    """3 articles valides sur 5 entrées (1 sans titre, 1 sans URL HTTP)."""
    articles = _rss_articles()
    assert len(articles) == 3


def test_rss_first_article_title():
    articles = _rss_articles()
    assert "NGAP" in articles[0].title


def test_rss_first_article_url():
    articles = _rss_articles()
    assert articles[0].url.startswith("https://")


def test_rss_published_at_is_datetime():
    articles = _rss_articles()
    for a in articles:
        assert a.published_at is None or isinstance(a.published_at, datetime)


def test_rss_summary_raw_truncated():
    articles = _rss_articles()
    for a in articles:
        if a.summary_raw:
            assert len(a.summary_raw) <= 500


def test_rss_no_empty_titles():
    articles = _rss_articles()
    for a in articles:
        assert a.title.strip() != ""


def test_rss_all_urls_http():
    articles = _rss_articles()
    for a in articles:
        assert a.url.startswith("http")


def test_rss_bozo_feed_does_not_crash():
    """Un flux malformé ne doit pas lever d'exception."""
    result = parse_rss(b"<not xml at all !!!>", "https://example.com/bad.rss")
    assert isinstance(result, list)


def test_rss_empty_feed():
    empty = b"""<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""
    result = parse_rss(empty, "https://example.com/empty.rss")
    assert result == []


# ──────────────────────────────────────────────────────────────
# HTML parser
# ──────────────────────────────────────────────────────────────

def _html_articles():
    content = (FIXTURES / "sample_html.html").read_text(encoding="utf-8")
    return parse_html(
        content,
        base_url="https://www.ordre-infirmiers.fr",
        selector="article.news-item",
        title_sel="h2",
        link_sel="a",
        date_sel="time",
        summary_sel="p.excerpt",
    )


def test_html_returns_list():
    articles = _html_articles()
    assert isinstance(articles, list)


def test_html_correct_count():
    """3 articles valides sur 4 (1 sans lien)."""
    articles = _html_articles()
    assert len(articles) == 3


def test_html_first_title():
    articles = _html_articles()
    assert "Élections" in articles[0].title


def test_html_urls_are_absolute():
    articles = _html_articles()
    for a in articles:
        assert a.url.startswith("http"), f"URL non absolue: {a.url}"


def test_html_dates_parsed():
    articles = _html_articles()
    dates = [a.published_at for a in articles if a.published_at]
    assert len(dates) == 3
    assert all(isinstance(d, datetime) for d in dates)


def test_html_summaries_present():
    articles = _html_articles()
    for a in articles:
        assert a.summary_raw is not None
        assert len(a.summary_raw) > 10


def test_html_summary_truncated():
    articles = _html_articles()
    for a in articles:
        if a.summary_raw:
            assert len(a.summary_raw) <= 500


def test_html_unknown_selector_returns_empty():
    content = (FIXTURES / "sample_html.html").read_text(encoding="utf-8")
    result = parse_html(
        content,
        base_url="https://example.com",
        selector="div.does-not-exist",
    )
    assert result == []


def test_html_no_empty_titles():
    articles = _html_articles()
    for a in articles:
        assert a.title.strip() != ""
