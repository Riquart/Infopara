from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from datetime import datetime
from typing import Optional, Any
from urllib.parse import urlparse

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.models import Article, Source, SourceKind
from app.parsers.html import RawArticle as HtmlRawArticle
from app.parsers.html import parse_html
from app.parsers.rss import RawArticle as RssRawArticle
from app.parsers.rss import parse_rss
from app.tagger import tag_article

USER_AGENT = "InfoPara/1.0 (+contact: benoit.riquart@cgm.com)"
REQUEST_TIMEOUT = 20.0
RATE_LIMIT_DELAY = 1.1  # seconds between requests to the same domain

_last_request_time: dict[str, float] = defaultdict(float)


def _rate_limit(url: str) -> None:
    domain = urlparse(url).netloc
    elapsed = time.monotonic() - _last_request_time[domain]
    if elapsed < RATE_LIMIT_DELAY:
        time.sleep(RATE_LIMIT_DELAY - elapsed)
    _last_request_time[domain] = time.monotonic()


def fetch_source(source: Source, db: Session) -> int:
    """Fetch a single source, persist new articles. Returns count of new articles."""
    logger.info("Fetching source: {} ({})", source.name, source.url)
    _rate_limit(source.url)

    try:
        with httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = client.get(source.url)
    except httpx.TimeoutException:
        _record_error(source, db, "Timeout après {}s".format(REQUEST_TIMEOUT))
        return 0
    except httpx.RequestError as exc:
        _record_error(source, db, f"Erreur réseau : {exc}")
        return 0

    if response.status_code == 404:
        _record_error(source, db, "HTTP 404 — URL introuvable")
        return 0
    if response.status_code == 403:
        _record_error(source, db, "HTTP 403 — Accès refusé")
        return 0
    if response.status_code >= 400:
        _record_error(source, db, f"HTTP {response.status_code}")
        return 0

    try:
        if source.kind == SourceKind.rss:
            raw_articles = parse_rss(response.content, source.url)
        else:
            raw_articles = parse_html(
                response.text,
                base_url=source.url,
                selector=source.selector or "article",
                title_sel=source.title_sel,
                link_sel=source.link_sel,
                date_sel=source.date_sel,
                summary_sel=source.summary_sel,
            )
    except Exception as exc:
        _record_error(source, db, f"Erreur parsing : {exc}")
        return 0

    new_count = 0
    for raw in raw_articles:
        if _persist_article(raw, source, db):
            new_count += 1

    source.last_fetched_at = datetime.utcnow()
    source.last_error = None
    db.commit()

    logger.info(
        "Source '{}': {} articles trouvés, {} nouveaux", source.name, len(raw_articles), new_count
    )
    return new_count


def fetch_all_sources(db: Session) -> dict[str, int]:
    """Fetch all active sources. Returns {source_name: new_articles_count}."""
    sources = db.query(Source).filter(Source.active == True).all()  # noqa: E712
    results: dict[str, int] = {}
    for source in sources:
        results[source.name] = fetch_source(source, db)
    return results


def _persist_article(
    raw: RssRawArticle | HtmlRawArticle,
    source: Source,
    db: Session,
) -> bool:
    """Insert article if not already present. Returns True if new."""
    url_hash = _make_hash(raw.url, raw.title)

    existing = db.query(Article).filter(Article.url_hash == url_hash).first()
    if existing:
        return False

    thematic_tags, profession_tags = tag_article(
        title=raw.title,
        url=raw.url,
        default_tags=source.default_tags,
        default_profession_tags=source.default_profession_tags,
    )

    article = Article(
        source_id=source.id,
        url=raw.url,
        url_hash=url_hash,
        title=raw.title,
        published_at=raw.published_at,
        fetched_at=datetime.utcnow(),
        summary_raw=raw.summary_raw,
    )
    article.tags = thematic_tags
    article.profession_tags = profession_tags

    db.add(article)
    try:
        db.flush()
        return True
    except Exception:
        db.rollback()
        return False


def _make_hash(url: str, title: str) -> str:
    canonical_url = url.strip().rstrip("/").lower()
    normalized_title = " ".join(title.strip().lower().split())
    raw = f"{canonical_url}|{normalized_title}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _record_error(source: Source, db: Session, error: str) -> None:
    logger.warning("Source '{}' erreur: {}", source.name, error)
    source.last_error = error
    source.last_fetched_at = datetime.utcnow()
    db.commit()
