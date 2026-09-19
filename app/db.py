from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base

import os

from loguru import logger

#: Chemin par defaut de la base (a cote du code).
DB_PATH_DEFAUT = Path(__file__).parent.parent / "veille.db"


def _resoudre_chemin() -> Path:
    """Determine le chemin de la base sans jamais faire echouer le demarrage.

    INFOPARA_DB permet de viser un volume persistant. Si ce chemin est
    inutilisable (volume absent, dossier non monte, droits insuffisants), on
    se replie sur le chemin par defaut plutot que de planter : au pire la base
    est ephemere, mais le service reste en ligne.
    """
    brut = (os.environ.get("INFOPARA_DB") or "").strip()
    if not brut:
        return DB_PATH_DEFAUT

    chemin = Path(brut)
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        # Verifie qu'on peut reellement ecrire a cet endroit.
        chemin.touch(exist_ok=True)
    except OSError as exc:
        logger.warning(
            "INFOPARA_DB={} inutilisable ({}) : repli sur {} "
            "(la base sera ephemere)", chemin, exc, DB_PATH_DEFAUT,
        )
        return DB_PATH_DEFAUT

    logger.info("Base de donnees : {}", chemin)
    return chemin


DB_PATH = _resoudre_chemin()
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
