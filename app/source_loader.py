from __future__ import annotations

from pathlib import Path

import yaml
from loguru import logger
from sqlalchemy.orm import Session

from app.models import Source, SourceCategory, SourceKind

SOURCES_PATH = Path(__file__).parent.parent / "sources.yaml"


def load_sources_from_yaml(db: Session) -> None:
    """Upsert sources from sources.yaml into the database."""
    with open(SOURCES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for entry in data.get("sources", []):
        if entry.get("active") is False:
            continue

        url = entry["url"]
        existing = db.query(Source).filter(Source.url == url).first()

        if existing:
            _update_source(existing, entry)
        else:
            source = _build_source(entry)
            db.add(source)
            logger.info("Nouvelle source ajoutée: {}", entry["name"])

    db.commit()
    total = db.query(Source).filter(Source.active == True).count()  # noqa: E712
    logger.info("{} sources actives en base", total)


def _build_source(entry: dict) -> Source:
    source = Source(
        name=entry["name"],
        url=entry["url"],
        kind=SourceKind(entry["kind"]),
        category=SourceCategory(entry["category"]),
        selector=entry.get("selector"),
        title_sel=entry.get("title_sel"),
        link_sel=entry.get("link_sel"),
        date_sel=entry.get("date_sel"),
        summary_sel=entry.get("summary_sel"),
        active=entry.get("active", True),
    )
    source.default_tags = entry.get("default_tags", [])
    source.default_profession_tags = entry.get("default_profession_tags", [])
    return source


def _update_source(source: Source, entry: dict) -> None:
    source.name = entry["name"]
    source.kind = SourceKind(entry["kind"])
    source.category = SourceCategory(entry["category"])
    source.selector = entry.get("selector")
    source.title_sel = entry.get("title_sel")
    source.link_sel = entry.get("link_sel")
    source.date_sel = entry.get("date_sel")
    source.summary_sel = entry.get("summary_sel")
    source.active = entry.get("active", True)
    source.default_tags = entry.get("default_tags", [])
    source.default_profession_tags = entry.get("default_profession_tags", [])
