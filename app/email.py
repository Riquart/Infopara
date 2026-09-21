"""Envoi d'emails via Mailjet, avec trace systematique.

Meme convention de variables que le portail et que bdc-vega :

    MJ_APIKEY_PUBLIC, MJ_APIKEY_PRIVATE, MAIL_FROM_EMAIL, MAIL_FROM_NAME

Absentes, InfoPara reste parfaitement fonctionnel : les envois sont marques
« non_configure » au lieu d'echouer.
"""
from __future__ import annotations

import html as _html
import os

import httpx
from loguru import logger

API_MAILJET = "https://api.mailjet.com/v3.1/send"
DELAI = 20.0

# Identite visuelle, reprise du logo VEGA.
NAVY = "#0B3A57"
CYAN = "#00AEEF"

CLE_PUBLIQUE = os.environ.get("MJ_APIKEY_PUBLIC", "").strip()
CLE_PRIVEE = os.environ.get("MJ_APIKEY_PRIVATE", "").strip()
EXPEDITEUR = os.environ.get("MAIL_FROM_EMAIL", "").strip()
NOM_EXPEDITEUR = os.environ.get("MAIL_FROM_NAME", "InfoPara").strip()
REPONSE_A = os.environ.get("MAIL_REPLY_TO", "").strip()


def etat_configuration() -> dict:
    manquantes = []
    if not CLE_PUBLIQUE:
        manquantes.append("MJ_APIKEY_PUBLIC")
    if not CLE_PRIVEE:
        manquantes.append("MJ_APIKEY_PRIVATE")
    if not EXPEDITEUR:
        manquantes.append("MAIL_FROM_EMAIL")
    return {
        "pret": not manquantes,
        "manquantes": manquantes,
        "expediteur": EXPEDITEUR or "(non defini)",
        "nom_expediteur": NOM_EXPEDITEUR,
    }


def _e(texte) -> str:
    """Echappe une valeur avant de l'inserer dans le HTML."""
    return _html.escape(str(texte or ""))


def gabarit_html(titre: str, contenu: str, pied: str = "") -> str:
    if not pied:
        pied = "Message envoye depuis InfoPara."
    return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:24px;background:#f1f5f9;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" cellpadding="0" cellspacing="0" style="max-width:620px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e2e8f0;">
    <tr><td style="background:{NAVY};padding:20px 28px;">
      <span style="color:#ffffff;font-size:17px;font-weight:700;letter-spacing:-0.2px;">InfoPara</span>
    </td></tr>
    <tr><td style="height:3px;background:{CYAN};"></td></tr>
    <tr><td style="padding:28px;">
      <h1 style="margin:0 0 18px;font-size:19px;line-height:1.35;color:{NAVY};font-weight:700;">{titre}</h1>
      <div style="font-size:14px;line-height:1.6;color:#334155;">{contenu}</div>
    </td></tr>
    <tr><td style="padding:16px 28px 22px;border-top:1px solid #f1f5f9;">
      <p style="margin:0;font-size:11px;line-height:1.5;color:#94a3b8;">{pied}</p>
    </td></tr>
  </table>
</body>
</html>"""


def envoyer(
    db,
    destinataires: list[str],
    sujet: str,
    corps_texte: str,
    corps_html: str | None = None,
    gabarit: str = "",
    nb_articles: int = 0,
):
    """Trace puis envoie. **Ne leve jamais d'exception.**

    Retourne la trace ; son champ `statut` dit ce qui s'est passe.
    """
    from app.models import EnvoiEmail

    destinataires = [a.strip() for a in destinataires if a and a.strip()]
    trace = EnvoiEmail(
        destinataires=", ".join(destinataires),
        sujet=sujet[:255],
        corps=corps_texte,
        gabarit=gabarit,
        nb_articles=nb_articles,
        statut="en_attente",
    )
    db.add(trace)
    db.commit()   # l'intention est enregistree avant toute tentative

    etat = etat_configuration()
    if not etat["pret"]:
        trace.statut = "non_configure"
        trace.erreur = "Configuration incomplete : " + ", ".join(etat["manquantes"])
        db.commit()
        logger.warning("Email non envoye : configuration incomplete ({})", ", ".join(etat["manquantes"]))
        return trace

    if not destinataires:
        trace.statut = "erreur"
        trace.erreur = "Aucun destinataire."
        db.commit()
        return trace

    message: dict = {
        "From": {"Email": EXPEDITEUR, "Name": NOM_EXPEDITEUR},
        "To": [{"Email": a} for a in destinataires],
        "Subject": sujet,
        "TextPart": corps_texte,
    }
    if corps_html:
        message["HTMLPart"] = corps_html
    if REPONSE_A:
        message["ReplyTo"] = {"Email": REPONSE_A}

    try:
        reponse = httpx.post(
            API_MAILJET, auth=(CLE_PUBLIQUE, CLE_PRIVEE),
            json={"Messages": [message]}, timeout=DELAI,
        )
        charge = {}
        try:
            charge = reponse.json()
        except Exception:
            pass

        if reponse.status_code in (200, 201):
            premier = (charge.get("Messages") or [{}])[0]
            if premier.get("Status") == "success":
                trace.statut = "envoye"
                trace.message_id = str((premier.get("To") or [{}])[0].get("MessageID", ""))
                from datetime import datetime
                trace.envoye_le = datetime.utcnow()
                logger.info("Recapitulatif envoye a {} ({} article(s))", trace.destinataires, nb_articles)
            else:
                trace.statut = "erreur"
                trace.erreur = str(premier.get("Errors") or charge)[:1000]
                logger.warning("Mailjet a refuse l'envoi : {}", trace.erreur[:200])
        else:
            trace.statut = "erreur"
            trace.erreur = f"HTTP {reponse.status_code} - {str(charge)[:900]}"
            logger.warning("Mailjet a repondu {}", reponse.status_code)
    except Exception as exc:
        trace.statut = "erreur"
        trace.erreur = f"{type(exc).__name__} : {exc}"[:1000]
        logger.warning("Echec de l'envoi ({})", trace.erreur[:200])

    db.commit()
    return trace


def recap_articles(articles, message_personnel: str = "") -> tuple[str, str, str]:
    """Construit le recapitulatif : (sujet, texte, html)."""
    n = len(articles)
    titre = f"{n} information{'s' if n > 1 else ''} a retenir"
    lien_site = os.environ.get("INFOPARA_URL", "https://www.iavega.fr/infopara").rstrip("/")

    # --- version texte ---
    lignes = []
    if message_personnel:
        lignes += [message_personnel, ""]
    for a in articles:
        quand = a.published_at.strftime("%d/%m/%Y") if a.published_at else ""
        source = a.source.name if getattr(a, "source", None) else ""
        lignes.append(f"- {a.title}")
        lignes.append(f"  {source}{' · ' if source and quand else ''}{quand}")
        if a.summary_raw:
            resume = " ".join(a.summary_raw.split())[:280]
            lignes.append(f"  {resume}")
        lignes.append(f"  {a.url}")
        lignes.append("")
    texte = "\n".join(lignes)

    # --- version HTML ---
    bloc_message = ""
    if message_personnel:
        bloc_message = (
            '<div style="background:#f8fafc;border-left:3px solid ' + CYAN + ';'
            'padding:12px 16px;border-radius:0 8px 8px 0;margin-bottom:22px;'
            'white-space:pre-wrap">' + _e(message_personnel) + "</div>"
        )

    cartes = []
    for a in articles:
        quand = a.published_at.strftime("%d/%m/%Y") if a.published_at else ""
        source = a.source.name if getattr(a, "source", None) else ""
        meta = " · ".join(x for x in (source, quand) if x)
        resume = " ".join((a.summary_raw or "").split())[:300]
        cartes.append(
            '<tr><td style="padding:0 0 16px">'
            '<div style="border:1px solid #e2e8f0;border-radius:10px;padding:16px 18px;">'
            f'<div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;'
            f'letter-spacing:0.4px;margin-bottom:6px">{_e(meta)}</div>'
            f'<a href="{_e(a.url)}" style="color:{NAVY};font-size:15px;font-weight:700;'
            f'text-decoration:none;line-height:1.4">{_e(a.title)}</a>'
            + (f'<p style="margin:9px 0 0;font-size:13px;line-height:1.55;color:#475569">'
               f'{_e(resume)}</p>' if resume else "")
            + f'<p style="margin:11px 0 0;font-size:12.5px"><a href="{_e(a.url)}" '
              f'style="color:{CYAN};text-decoration:none;font-weight:600">Lire l\'article →</a></p>'
            "</div></td></tr>"
        )

    contenu = (
        bloc_message
        + '<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%">'
        + "".join(cartes)
        + "</table>"
        + f'<p style="margin:18px 0 0;font-size:12px;color:#94a3b8">'
          f'Retrouvez toute la veille sur <a href="{_e(lien_site)}" '
          f'style="color:{CYAN};text-decoration:none">{_e(lien_site)}</a>.</p>'
    )

    return titre, texte, gabarit_html(titre, contenu)
