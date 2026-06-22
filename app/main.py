from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, List, Optional

from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db import get_db, init_db
from app.fetcher import fetch_all_sources, fetch_source
from app.models import Article, Source, SourceCategory, SourceKind, UserPref
from app.scheduler import start_scheduler, stop_scheduler
from app.source_detector import detect
from app.source_loader import load_sources_from_yaml, append_source_to_yaml

app = FastAPI(title="InfoPara", version="0.1.0")


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    sid = request.cookies.get(SESSION_COOKIE)
    new_session = sid is None
    if new_session:
        sid = str(uuid.uuid4())
    request.state.session_id = sid
    response = await call_next(request)
    if new_session:
        response.set_cookie(
            SESSION_COOKIE, sid,
            max_age=365 * 24 * 3600,
            httponly=True,
            samesite="lax",
        )
    return response

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

SESSION_COOKIE = "infopara_session"


def _urlencode_filters(filters: dict) -> str:
    return urlencode({k: v for k, v in filters.items() if v})


templates.env.filters["urlencode_filters"] = _urlencode_filters


def get_or_create_session(request: Request, response: Response) -> str:
    """Read session id from cookie, or create one. Works via middleware."""
    return getattr(request.state, "session_id", "")

PROFESSIONS = ["infirmier", "kinesitherapeute", "orthophoniste", "orthoptiste", "pedicure-podologue"]
TAGS = [
    "facturation", "NGAP/CCAM", "convention", "télétransmission/SESAM-Vitale",
    "logiciels-métier", "réglementation", "JO/décrets", "syndical", "ordre",
    "formation/DPC", "URSSAF/CARPIMKO", "démographie", "télésanté",
    "coopération-interpro", "actualité-générale",
]
CATEGORIES = [c.value for c in SourceCategory]


def get_or_create_session(request: Request, response: Response) -> str:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        sid = str(uuid.uuid4())
        response.set_cookie(
            SESSION_COOKIE, sid,
            max_age=365 * 24 * 3600,
            httponly=True,
            samesite="lax",
        )
    return sid


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
    session_id: str,
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
        hidden_subq = (
            db.query(UserPref.id)
            .filter(
                UserPref.session_id == session_id,
                UserPref.article_id == Article.id,
                UserPref.is_hidden == True,  # noqa: E712
            )
            .exists()
        )
        query = query.filter(~hidden_subq)

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


def _get_prefs(db: Session, session_id: str, article_ids: List[int]) -> dict:
    """Return a dict {article_id: UserPref} for the current session."""
    if not session_id or not article_ids:
        return {}
    rows = (
        db.query(UserPref)
        .filter(UserPref.session_id == session_id, UserPref.article_id.in_(article_ids))
        .all()
    )
    return {p.article_id: p for p in rows}


def _upsert_pref(db: Session, session_id: str, article_id: int, **fields) -> UserPref:
    """Get or create a UserPref row and update the given fields."""
    pref = (
        db.query(UserPref)
        .filter(UserPref.session_id == session_id, UserPref.article_id == article_id)
        .first()
    )
    if pref is None:
        pref = UserPref(session_id=session_id, article_id=article_id)
        db.add(pref)
    for k, v in fields.items():
        setattr(pref, k, v)
    db.commit()
    db.refresh(pref)
    return pref


def _counters(db: Session) -> dict:
    now = datetime.utcnow()
    def count_since(days: int) -> int:
        since = now - timedelta(days=days)
        return (
            db.query(func.count(Article.id))
            .filter(Article.fetched_at >= since)
            .scalar() or 0
        )

    by_profession: dict = {}
    for p in PROFESSIONS:
        by_profession[p] = (
            db.query(func.count(Article.id))
            .filter(Article._profession_tags.contains(p))
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
    session_id: str = Depends(get_or_create_session),
    profession: Optional[str] = None,
    tag: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
):
    per_page = 30
    base_query = _build_article_query(db, session_id, profession, tag, category, date_from, date_to, q)
    total = base_query.count()
    articles = (
        base_query
        .order_by(Article.published_at.desc().nullslast(), Article.fetched_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    prefs = _get_prefs(db, session_id, [a.id for a in articles])

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "articles": articles,
            "prefs": prefs,
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
    session_id: str = Depends(get_or_create_session),
    profession: Optional[str] = None,
    tag: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
):
    per_page = 30
    base_query = _build_article_query(db, session_id, profession, tag, category, date_from, date_to, q)
    total = base_query.count()
    articles = (
        base_query
        .order_by(Article.published_at.desc().nullslast(), Article.fetched_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    prefs = _get_prefs(db, session_id, [a.id for a in articles])

    return templates.TemplateResponse(
        "_articles_list.html",
        {
            "request": request,
            "articles": articles,
            "prefs": prefs,
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
def mark_read(
    article_id: int,
    db: Session = Depends(get_db),
    session_id: str = Depends(get_or_create_session),
):
    article = db.get(Article, article_id)
    if not article:
        return HTMLResponse("", status_code=404)
    current_pref = (
        db.query(UserPref)
        .filter(UserPref.session_id == session_id, UserPref.article_id == article_id)
        .first()
    )
    is_read = not (current_pref.is_read if current_pref else False)
    pref = _upsert_pref(db, session_id, article_id, is_read=is_read)
    return _article_card_response(article, {article_id: pref})


@app.post("/articles/{article_id}/star", response_class=HTMLResponse)
def toggle_star(
    article_id: int,
    db: Session = Depends(get_db),
    session_id: str = Depends(get_or_create_session),
):
    article = db.get(Article, article_id)
    if not article:
        return HTMLResponse("", status_code=404)
    current_pref = (
        db.query(UserPref)
        .filter(UserPref.session_id == session_id, UserPref.article_id == article_id)
        .first()
    )
    is_starred = not (current_pref.is_starred if current_pref else False)
    pref = _upsert_pref(db, session_id, article_id, is_starred=is_starred)
    return _article_card_response(article, {article_id: pref})


@app.post("/articles/{article_id}/hide", response_class=HTMLResponse)
def hide_article(
    article_id: int,
    db: Session = Depends(get_db),
    session_id: str = Depends(get_or_create_session),
):
    article = db.get(Article, article_id)
    if article:
        _upsert_pref(db, session_id, article_id, is_hidden=True)
    return HTMLResponse("")  # HTMX swap removes the card


def _article_card_response(article: Article, prefs: dict) -> HTMLResponse:
    html = templates.get_template("_article_card.html").render(
        {"article": article, "prefs": prefs, "request": None}
    )
    return HTMLResponse(html)


# ──────────────────────────────────────────────────────────────────────────────
# Sources view
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/sources", response_class=HTMLResponse)
def sources_view(request: Request, db: Session = Depends(get_db)):
    sources = db.query(Source).order_by(Source.category, Source.name).all()
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
# Add source
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/sources/detect", response_class=HTMLResponse)
def detect_source(request: Request, url: str = Form(...)):
    result = detect(url)
    return templates.TemplateResponse(
        "_source_detect_result.html",
        {"request": request, "r": result, "professions": PROFESSIONS, "categories": CATEGORIES},
    )


@app.post("/sources/add", response_class=HTMLResponse)
def add_source(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    url: str = Form(...),
    kind: str = Form(...),
    category: str = Form(...),
    selector: str = Form(""),
    title_sel: str = Form(""),
    link_sel: str = Form(""),
    date_sel: str = Form(""),
    summary_sel: str = Form(""),
    profession_tags: List[str] = Form(default=[]),
):
    existing = db.query(Source).filter(Source.url == url).first()
    if existing:
        return HTMLResponse(
            '<p class="text-amber-600 text-sm font-medium">⚠ Cette URL est déjà présente en base.</p>'
        )

    entry = {
        "name": name, "url": url, "kind": kind, "category": category,
        "selector": selector or None,
        "title_sel": title_sel or None,
        "link_sel": link_sel or None,
        "date_sel": date_sel or None,
        "summary_sel": summary_sel or None,
        "default_tags": [],
        "default_profession_tags": profession_tags,
        "active": True,
    }

    from app.source_loader import _build_source
    source = _build_source(entry)
    db.add(source)
    db.commit()
    db.refresh(source)

    append_source_to_yaml(entry)

    from app.fetcher import fetch_source as _fetch
    new_count = _fetch(source, db)

    error_html = ""
    if source.last_error:
        error_html = f'<p class="text-amber-600 text-xs mt-1">⚠ {source.last_error}</p>'

    return HTMLResponse(f"""
        <div class="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          <p class="font-semibold">✓ Source « {name} » ajoutée</p>
          <p class="text-xs mt-0.5">{new_count} articles collectés au premier fetch</p>
          {error_html}
          <p class="text-xs mt-2 text-emerald-600">
            <a href="/sources" class="underline hover:no-underline">Voir toutes les sources →</a>
          </p>
        </div>
    """)


# ──────────────────────────────────────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/export/csv")
def export_csv(
    request: Request,
    db: Session = Depends(get_db),
    session_id: str = Depends(get_or_create_session),
    profession: Optional[str] = None,
    tag: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
):
    articles = (
        _build_article_query(db, session_id, profession, tag, category, date_from, date_to, q)
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
        headers={"Content-Disposition": "attachment; filename=infopara.csv"},
    )


@app.get("/export/opml")
def export_opml(db: Session = Depends(get_db)):
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
        headers={"Content-Disposition": "attachment; filename=infopara-sources.opml"},
    )
