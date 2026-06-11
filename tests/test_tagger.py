"""Tests du moteur de tagging basé sur tagging_rules.yaml."""
from __future__ import annotations

import pytest

from app.tagger import tag_article


def tag(title: str, url: str = "https://example.com/article", defaults=None, prof_defaults=None):
    return tag_article(
        title=title,
        url=url,
        default_tags=defaults or [],
        default_profession_tags=prof_defaults or [],
    )


# ──────────────────────────────────────────────────────────────
# Profession detection
# ──────────────────────────────────────────────────────────────

def test_profession_infirmier_from_title():
    _, profs = tag("Revalorisation des actes infirmiers libéraux")
    assert "infirmier" in profs


def test_profession_idel_acronym():
    _, profs = tag("Nouvelle circulaire pour les IDEL en 2024")
    assert "infirmier" in profs


def test_profession_kine_from_title():
    _, profs = tag("Convention nationale des masseurs-kinésithérapeutes")
    assert "kinesitherapeute" in profs


def test_profession_kine_acronym_mk():
    _, profs = tag("Réforme de la formation initiale MK")
    assert "kinesitherapeute" in profs


def test_profession_orthophoniste():
    _, profs = tag("Bilan de langage : nouvelles recommandations HAS pour les orthophonistes")
    assert "orthophoniste" in profs


def test_profession_orthoptiste():
    _, profs = tag("Décret portant sur les actes des orthoptistes")
    assert "orthoptiste" in profs


def test_profession_podologue():
    _, profs = tag("URSSAF : cotisations des pédicures-podologues 2024")
    assert "pedicure-podologue" in profs


def test_profession_default_inherited():
    _, profs = tag("Actualité générale santé", prof_defaults=["infirmier"])
    assert "infirmier" in profs


def test_profession_multiple_detected():
    _, profs = tag("Coopération infirmière et kinésithérapeute en MSP")
    assert "infirmier" in profs
    assert "kinesitherapeute" in profs


# ──────────────────────────────────────────────────────────────
# Thematic tags
# ──────────────────────────────────────────────────────────────

def test_tag_facturation_ngap():
    tags, _ = tag("Mise à jour de la NGAP : nouvelles cotations")
    assert "facturation" in tags or "NGAP/CCAM" in tags


def test_tag_convention():
    tags, _ = tag("Signature de l'avenant 9 à la convention nationale infirmière")
    assert "convention" in tags


def test_tag_sesamvitale():
    tags, _ = tag("Mise à jour SESAM-Vitale obligatoire pour les IDE")
    assert "télétransmission/SESAM-Vitale" in tags


def test_tag_jo_decret():
    tags, _ = tag("Décret n°2024-123 publié au Journal Officiel")
    assert "JO/décrets" in tags


def test_tag_dpc():
    tags, _ = tag("Nouvelles actions DPC disponibles pour les infirmiers")
    assert "formation/DPC" in tags


def test_tag_urssaf():
    tags, _ = tag("URSSAF : calendrier des cotisations sociales 2024")
    assert "URSSAF/CARPIMKO" in tags


def test_tag_telesante():
    tags, _ = tag("Télésoin : bilan d'étape pour les kinésithérapeutes")
    assert "télésanté" in tags


def test_tag_logiciel_from_url():
    tags, _ = tag(
        "Nouvelle version disponible",
        url="https://pro.maiia.com/blog/version-3-2",
    )
    assert "logiciels-métier" in tags


def test_tag_syndical():
    tags, _ = tag("Le syndicat FFMKR appelle à la mobilisation nationale")
    assert "syndical" in tags


def test_tag_ordre():
    tags, _ = tag("L'Ordre national des infirmiers publie son rapport annuel")
    assert "ordre" in tags


def test_tag_catch_all_when_no_specific():
    tags, _ = tag("Bonne journée à tous", url="https://example.com/hello")
    assert "actualité-générale" in tags


def test_tag_no_catch_all_when_specific():
    tags, _ = tag("Avenant convention kinésithérapeutes signé")
    assert "actualité-générale" not in tags


def test_default_tags_inherited():
    tags, _ = tag("Quelque chose de très générique", defaults=["réglementation"])
    assert "réglementation" in tags


def test_tags_are_sorted():
    tags, profs = tag("NGAP convention infirmiers URSSAF DPC")
    assert tags == sorted(tags)
    assert profs == sorted(profs)
