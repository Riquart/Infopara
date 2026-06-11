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


def append_source_to_yaml(entry: dict) -> None:
    """Append a new source entry to sources.yaml (UI-added sources section)."""
    with open(SOURCES_PATH, encoding="utf-8") as f:
        content = f.read()

    # Build a clean YAML block for this source
    block_lines = ["\n  # Ajoutée via l'interface", f"  - name: {yaml.dump(entry['name'], allow_unicode=True).strip()}"]
    block_lines.append(f"    url: {yaml.dump(entry['url'], allow_unicode=True).strip()}")
    block_lines.append(f"    kind: {entry['kind']}")
    block_lines.append(f"    category: {entry['category']}")
    if entry.get("selector"):
        block_lines.append(f"    selector: {yaml.dump(entry['selector'], allow_unicode=True).strip()}")
    if entry.get("title_sel"):
        block_lines.append(f"    title_sel: {yaml.dump(entry['title_sel'], allow_unicode=True).strip()}")
    if entry.get("link_sel"):
        block_lines.append(f"    link_sel: {yaml.dump(entry['link_sel'], allow_unicode=True).strip()}")
    if entry.get("date_sel"):
        block_lines.append(f"    date_sel: {yaml.dump(entry['date_sel'], allow_unicode=True).strip()}")
    if entry.get("summary_sel"):
        block_lines.append(f"    summary_sel: {yaml.dump(entry['summary_sel'], allow_unicode=True).strip()}")
    block_lines.append(f"    default_tags: {yaml.dump(entry.get('default_tags', []), allow_unicode=True).strip()}")
    block_lines.append(f"    default_profession_tags: {yaml.dump(entry.get('default_profession_tags', []), allow_unicode=True).strip()}")
    block_lines.append("    active: true")

    # Insert before the TODO comment block or at the end of sources list
    todo_marker = "  # ──────────────────────────────────────────────────────────────\n  # SOURCES EN ATTENTE"
    block = "\n".join(block_lines) + "\n"
    if todo_marker in content:
        content = content.replace(todo_marker, block + "\n" + todo_marker)
    else:
        content = content.rstrip() + "\n" + block

    with open(SOURCES_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Source '{}' ajoutée dans sources.yaml", entry["name"])


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
