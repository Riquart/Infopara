"""Expose InfoPara sous son sous-chemin /infopara.

Le portail du domaine vit desormais dans un service distinct
(portail.iavega.fr). Ce fichier ne s'occupe plus que de l'application :
son adresse publique reste www.iavega.fr/infopara.

La racine du service redirige vers /infopara/ : rien d'autre n'est expose.

Le montage sous /infopara est indispensable : il renseigne root_path, qui sert
a construire les liens des gabarits (/infopara/sources, /infopara/export/...).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.main import app as infopara_app


@asynccontextmanager
async def lifespan(application):
    """Enchaine le cycle de vie d'InfoPara.

    Monter une application ne declenche pas son lifespan : sans ce bloc,
    init_db() et le planificateur ne demarreraient jamais.
    """
    async with infopara_app.router.lifespan_context(infopara_app):
        yield


app = FastAPI(title="InfoPara", lifespan=lifespan)
app.mount("/infopara", infopara_app)


@app.get("/", include_in_schema=False)
def accueil() -> RedirectResponse:
    """La racine du service n'expose rien : elle renvoie vers l'application."""
    return RedirectResponse("/infopara/", status_code=307)
