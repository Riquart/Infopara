"""Portail iavega.fr.

Sert la page d'accueil du domaine et monte l'application InfoPara
sous /infopara. Un seul service Railway suffit donc pour les deux.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.main import app as infopara_app


@asynccontextmanager
async def lifespan(application):
    """Enchaine le cycle de vie d'InfoPara.

    Monter une application ne declenche pas son lifespan : sans ce bloc,
    init_db() et le planificateur ne demarreraient jamais.
    """
    async with infopara_app.router.lifespan_context(infopara_app):
        yield


app = FastAPI(title="iavega.fr", lifespan=lifespan)
app.mount("/infopara", infopara_app)


ACCUEIL = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IA VEGA</title>
<style>
  :root { --cyan:#00AEEF; --navy:#0B3A57; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         color:var(--navy); background:#fff; }
  main { max-width:44rem; margin:0 auto; padding:5rem 1.5rem; }
  h1 { font-size:2.2rem; margin:0 0 .4rem; letter-spacing:-.02em; }
  .filet { width:4rem; height:4px; background:var(--cyan); border-radius:2px; margin:1.2rem 0 2rem; }
  p.lead { font-size:1.05rem; line-height:1.65; color:#3d5566; }
  .carte { display:block; margin-top:2.5rem; padding:1.5rem; border:1px solid #e3e9ee;
           border-radius:14px; text-decoration:none; color:inherit; transition:.15s; }
  .carte:hover { border-color:var(--cyan); box-shadow:0 4px 18px rgba(0,174,239,.10); }
  .carte h2 { margin:0 0 .35rem; font-size:1.15rem; }
  .carte p { margin:0; color:#5b6b7b; font-size:.92rem; }
  footer { margin-top:4rem; font-size:.8rem; color:#8b9aa8; }
</style>
</head>
<body>
<main>
  <h1>IA VEGA</h1>
  <div class="filet"></div>
  <p class="lead">Outils d'information et d'aide a la decision pour les professions
  paramedicales liberales.</p>

  <a class="carte" href="/infopara/">
    <h2>InfoPara &rarr;</h2>
    <p>Veille documentaire pour infirmiers, kines, orthophonistes et orthoptistes.
       Sources filtrees, dedoublonnees et classees par profession.</p>
  </a>

  <footer>iavega.fr</footer>
</main>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def accueil() -> HTMLResponse:
    return HTMLResponse(ACCUEIL)
