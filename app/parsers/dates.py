"""Extraction de dates, robuste et prudente.

Remplace `dateutil.parser.parse(texte, fuzzy=True)`.

Pourquoi ce changement : `dateutil` ne connait pas les mois francais. Sur
« Publication publiee : 10 septembre 2026 », il ignorait « septembre », prenait
10 pour un MOIS, et completait le jour avec la date du jour. Resultat : une date
fausse et souvent dans le futur (10 septembre -> 2026-10-21).

Principes :
  1. Les formats sans ambiguite (ISO) sont traites en premier.
  2. Sinon on analyse avec `dateparser` en francais puis en anglais, en visant
     le passe (une actualite n'est pas publiee dans le futur).
  3. Un libelle avant deux-points est ecarte (« Publication publiee : ... »).
  4. Toute date implausible est REJETEE : mieux vaut pas de date qu'une date
     inventee. C'est ce controle qui aurait evite l'incident.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from dateparser import parse as dateparser_parse
from dateparser.search import search_dates
from loguru import logger

# Bornes de plausibilite.
ANCIENNETE_MAX = timedelta(days=3650)   # 10 ans en arriere
FUTUR_TOLERE = timedelta(days=1)        # petite tolerance de fuseau

REGLAGES = {
    "RETURN_AS_TIMEZONE_AWARE": False,
    "PREFER_DATES_FROM": "past",
    "DATE_ORDER": "DMY",
    "STRICT_PARSING": False,
}


def _maintenant() -> datetime:
    return datetime.now().replace(tzinfo=None)


def plausible(d: Optional[datetime]) -> bool:
    """Rejette les dates incoherentes, notamment celles dans le futur."""
    if d is None:
        return False
    maintenant = _maintenant()
    return (maintenant - ANCIENNETE_MAX) <= d <= (maintenant + FUTUR_TOLERE)


def _depuis_iso(texte: str) -> Optional[datetime]:
    """Formats normalises : 2026-08-11, 2026-08-11T10:00:00+02:00, ..."""
    t = texte.strip()
    if not t:
        return None
    for variante in (t, t.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(variante).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def _depuis_langues(texte: str) -> Optional[datetime]:
    """Analyse en francais, puis en anglais."""
    for langues in (["fr"], ["en"]):
        try:
            d = dateparser_parse(texte, languages=langues, settings=REGLAGES)
        except Exception:
            d = None
        if d:
            return d.replace(tzinfo=None)
    return None


def _candidats(texte: str) -> list[str]:
    """Textes a essayer, du plus specifique au plus general."""
    t = texte.strip()
    trouves = []
    if ":" in t:
        apres = t.split(":")[-1].strip()
        if apres:
            trouves.append(apres)
    trouves.append(t)
    return trouves


def extraire_date(texte: Optional[str]) -> Optional[datetime]:
    """Retourne une date plausible, ou None."""
    if not texte:
        return None

    # 1 et 2 : ISO, puis analyse par langue sur les candidats.
    for candidat in _candidats(texte):
        d = _depuis_iso(candidat) or _depuis_langues(candidat)
        if plausible(d):
            return d

    # 3 : recherche dans un texte plus long, en exigeant un chiffre dans le
    #     fragment retenu (« Publie le 3 octobre 2025 »).
    for langues in (["fr"], ["en"]):
        try:
            trouves = search_dates(texte, languages=langues, settings=REGLAGES)
        except Exception:
            trouves = None
        for libelle, valeur in trouves or []:
            if valeur is None:
                continue
            if not any(c.isdigit() for c in (libelle or "")):
                continue
            propre = valeur.replace(tzinfo=None)
            if plausible(propre):
                return propre

    logger.debug("Aucune date plausible dans {!r}", texte[:120])
    return None
