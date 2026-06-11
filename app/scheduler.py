from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from app.db import SessionLocal
from app.fetcher import fetch_all_sources

_scheduler: BackgroundScheduler | None = None


def _run_fetch_job() -> None:
    logger.info("Scheduler: démarrage du fetch automatique")
    db = SessionLocal()
    try:
        results = fetch_all_sources(db)
        total = sum(results.values())
        logger.info("Scheduler: fetch terminé — {} nouveaux articles", total)
    except Exception as exc:
        logger.exception("Scheduler: erreur inattendue — {}", exc)
    finally:
        db.close()


def start_scheduler() -> None:
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="Europe/Paris")
    _scheduler.add_job(
        _run_fetch_job,
        trigger="interval",
        hours=2,
        id="fetch_all",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    _scheduler.start()
    logger.info("Scheduler démarré (job fetch toutes les 2h)")


def stop_scheduler() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler arrêté")
