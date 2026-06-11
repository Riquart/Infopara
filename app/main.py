from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from typing import Annotated, Optional

from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db import get_db, init_db
from app.fetcher import fetch_all_sources, fetch_source
from app.models import Article, Source, SourceCategory
from app.scheduler import start_scheduler, stop_scheduler
from app.source_loader import load_sources_from_yaml

app = FastAPI(title="InfoPara", version="0.1.0")

templates = Jinja2Templates(directory="app/templates")


def _urlencode_filters(filters: dict) -> str:
    return urlencode({k: v for k, v in filters.items() if v})


templates.env.filters["urlencode_filters"] = _urlencode_filters

PROFESSIONS = ["infirmier", "kinesitherapeute", "orthophoniste", "orthoptiste", "pedicure-podologue"]
TAGS = [
    "facturation", "NGAP/CCAM", "convention", "télétransmission/SESAM-Vitale",
    "logiciels-métier", "réglementation", "JO/décrets", "syndical", "ordre",
    "formation/DPC", "URSSAF/CARPIMKO", "démographie", "télésanté",
    "coopération-interpro", "actualité-générale",
]
CATEGORIES = [c.value for c in SourceCategory]


@app.on_event("startup")
def startup() -> None:
    init_db()
    db = next(get_db())
    load_sources_from_yaml(db)
    db.close()
    start_scheduler()
    logger.info("InfoPara démarré")


@app.on_event("shutdown")
def shutdown() -> None:
    stop_scheduler()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _build_article_query(
    db: Session,
    profession: Optional[str],
    tag: Optional[str],
    category: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    q: Optional[str],
    show_hidden: bool = False,
):
    query = db.query(Article).join(Source)

    if not show_hidden:
        query = query.filter(Article.is_hidden == False)  # noqa: E712

    if profession:
        query = query.filter(Article._profession_tags.contains(profession))
    else:
        # Exclure les articles sans aucun tag profession (trop génériques)
        query = query.filter(Article._profession_tags != "[]")

    if tag:
        query = query.filter(Article._tags.contains(tag))

    if category:
        query = query.filter(Source.category == category)

    if date_from:
        try:
            dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(Article.published_at >= dt)
        except ValueError:
            pass

    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Article.published_at < dt)
        except ValueError:
            pass

    if q:
        like = f"%{q}%"
        query = query.filter(Article.title.ilike(like))

    return query


def _counters(db: Session) -> dict:
    now = datetime.utcnow()
    def count_since(days: int) -> int:
        since = now - timedelta(days=days)
        return (
            db.query(func.count(Article.id))
            .filter(Article.fetched_at >= since, Article.is_hidden == False)  # noqa: E712
            .scalar() or 0
        )

    by_profession: dict[str, int] = {}
    for p in PROFESSIONS:
        by_profession[p] = (
            db.query(func.count(Article.id))
            .filter(Article._profession_tags.contains(p), Article.is_hidden == False)  # noqa: E712
            .scalar() or 0
        )

    return {
        "today": count_since(1),
        "week": count_since(7),
        "month": count_since(30),
        "by_profession": by_profession,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main dashboard
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    db: Session = Depends(get_db),
    profession: Optional[str] = None,
    tag: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
):
    per_page = 30
    base_query = _build_article_query(db, profession, tag, category, date_from, date_to, q)
    total = base_query.count()
    articles = (
        base_query
        .order_by(Article.published_at.desc().nullslast(), Article.fetched_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "articles": articles,
            "counters": _counters(db),
            "professions": PROFESSIONS,
            "tags": TAGS,
            "categories": CATEGORIES,
            "filters": {
                "profession": profession, "tag": tag, "category": category,
                "date_from": date_from, "date_to": date_to, "q": q,
            },
            "page": page,
            "total": total,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        },
    )


# HTMX partial for article list
@app.get("/articles", response_class=HTMLResponse)
def articles_partial(
    request: Request,
    db: Session = Depends(get_db),
    profession: Optional[str] = None,
    tag: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
):
    per_page = 30
    base_query = _build_article_query(db, profession, tag, category, date_from, date_to, q)
    total = base_query.count()
    articles = (
        base_query
        .order_by(Article.published_at.desc().nullslast(), Article.fetched_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return templates.TemplateResponse(
        "_articles_list.html",
        {
            "request": request,
            "articles": articles,
            "page": page,
            "total": total,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
            "filters": {
                "profession": profession, "tag": tag, "category": category,
                "date_from": date_from, "date_to": date_to, "q": q,
            },
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Article actions
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/articles/{article_id}/read", response_class=HTMLResponse)
def mark_read(article_id: int, db: Session = Depends(get_db)):
    article = db.get(Article, article_id)
    if article:
        article.is_read = not article.is_read
        db.commit()
    return _article_card_response(article)


@app.post("/articles/{article_id}/star", response_class=HTMLResponse)
def toggle_star(article_id: int, db: Session = Depends(get_db)):
    article = db.get(Article, article_id)
    if article:
        article.is_starred = not article.is_starred
        db.commit()
    return _article_card_response(article)


@app.post("/articles/{article_id}/hide", response_class=HTMLResponse)
def hide_article(article_id: int, db: Session = Depends(get_db)):
    article = db.get(Article, article_id)
    if article:
        article.is_hidden = True
        db.commit()
    return HTMLResponse("")  # HTMX swap removes the card


def _article_card_response(article: Article | None) -> HTMLResponse:
    if not article:
        return HTMLResponse("", status_code=404)
    html = templates.get_template("_article_card.html").render({"article": article, "request": None})
    return HTMLResponse(html)


# ──────────────────────────────────────────────────────────────────────────────
# Sources view
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/sources", response_class=HTMLResponse)
def sources_view(request: Request, db: Session = Depends(get_db)):
    sources = db.query(Source).order_by(Source.category, Source.name).all()
    # Attach article counts
    counts = dict(
        db.query(Article.source_id, func.count(Article.id))
        .group_by(Article.source_id)
        .all()
    )
    return templates.TemplateResponse(
        "sources.html",
        {"request": request, "sources": sources, "counts": counts},
    )


# ──────────────────────────────────────────────────────────────────────────────
# Refresh
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/refresh", response_class=HTMLResponse)
def refresh_all(request: Request, db: Session = Depends(get_db)):
    results = fetch_all_sources(db)
    total_new = sum(results.values())
    return HTMLResponse(
        f'<div class="text-green-600 font-semibold">✓ Fetch terminé — {total_new} nouveaux articles</div>'
    )


@app.post("/refresh/{source_id}", response_class=HTMLResponse)
def refresh_one(source_id: int, request: Request, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        return HTMLResponse('<div class="text-red-500">Source introuvable</div>', status_code=404)
    new_count = fetch_source(source, db)
    status = source.last_error or f"✓ {new_count} nouveaux articles"
    css = "text-red-500" if source.last_error else "text-green-600"
    return HTMLResponse(f'<span class="{css}">{status}</span>')


# ──────────────────────────────────────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/export/csv")
def export_csv(
    db: Session = Depends(get_db),
    profession: Optional[str] = None,
    tag: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
):
    articles = (
        _build_article_query(db, profession, tag, category, date_from, date_to, q)
        .order_by(Article.published_at.desc().nullslast())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "titre", "url", "source", "date_publication", "professions", "tags", "résumé"])
    for a in articles:
        writer.writerow([
            a.id, a.title, a.url, a.source.name,
            a.published_at.isoformat() if a.published_at else "",
            "|".join(a.profession_tags),
            "|".join(a.tags),
            (a.summary_raw or "").replace("\n", " "),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=veille-auxmed.csv"},
    )


@app.get("/export/opml")
def export_opml(db: Session = Depends(get_db)):
    from app.models import SourceKind
    rss_sources = db.query(Source).filter(
        Source.kind == SourceKind.rss, Source.active == True  # noqa: E712
    ).all()

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<opml version="2.0"><head><title>InfoPara — Sources RSS</title></head><body>',
    ]
    for s in rss_sources:
        name = s.name.replace('"', "&quot;")
        url = s.url.replace("&", "&amp;")
        lines.append(f'  <outline type="rss" text="{name}" xmlUrl="{url}"/>')
    lines.append("</body></opml>")

    return Response(
        content="\n".join(lines),
        media_type="text/x-opml",
        headers={"Content-Disposition": "attachment; filename=veille-auxmed-sources.opml"},
    )
