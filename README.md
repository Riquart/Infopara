# InfoPara

Dashboard de veille pour les **auxiliaires médicaux libéraux en France** — agrège les actualités issues de sources officielles, syndicales, presse professionnelle et éditeurs logiciels pour 5 professions : infirmiers (IDE), kinésithérapeutes, orthophonistes, orthoptistes, pédicures-podologues.

Pas de traitement IA — uniquement collecte, déduplication et tagging par mots-clés.

---

## Installation rapide

```bash
# 1. Cloner / se placer dans le dossier
cd veille-auxmed

# 2. Créer un environnement virtuel
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Installer les dépendances
pip install -e ".[dev]"

# 4. Lancer l'application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Au premier démarrage : création automatique de `veille.db` + chargement des sources depuis `sources.yaml`.

Ouvrir : http://localhost:8000

### Premier fetch manuel

Via le bouton **↻ Refresh now** dans la barre de navigation, ou en ligne de commande :

```bash
python -c "
from app.db import SessionLocal, init_db
from app.fetcher import fetch_all_sources
from app.source_loader import load_sources_from_yaml
init_db()
db = SessionLocal()
load_sources_from_yaml(db)
results = fetch_all_sources(db)
print(f'Total nouveaux articles : {sum(results.values())}')
db.close()
"
```

---

## Lancer les tests

```bash
pytest -v
```

Les tests utilisent uniquement des fixtures HTML/RSS locales (offline) — aucune requête réseau.

---

## Ajouter une source

Éditer `sources.yaml`. Deux cas :

### Source RSS (prioritaire)

```yaml
- name: "Nom affiché"
  url: "https://exemple.fr/feed.rss"
  kind: rss
  category: presse          # officiel | syndicat | ordre | presse | editeur
  default_tags: ["réglementation"]
  default_profession_tags: ["infirmier"]
  active: true
```

### Source HTML (scraping)

```yaml
- name: "Nom affiché"
  url: "https://exemple.fr/actualites"
  kind: html
  category: syndicat
  selector: "article.post"          # sélecteur CSS pointant sur chaque item
  title_sel: "h2, h3"               # sélecteur du titre dans l'item
  link_sel: "a.lire-plus, h2 a"     # sélecteur du lien
  date_sel: "time, .date"           # sélecteur de la date (optionnel)
  summary_sel: "p.excerpt"          # sélecteur du résumé (optionnel)
  default_tags: ["syndical"]
  default_profession_tags: ["kinesitherapeute"]
  active: true
```

Redémarrer l'application (ou appuyer sur **Refresh now**) — les nouvelles sources sont chargées automatiquement au démarrage.

---

## Ajouter une règle de tag

Éditer `tagging_rules.yaml`. Deux sections :

### Règle de profession

```yaml
profession_rules:
  - tag: infirmier
    patterns:
      - "infirmi(er|ère)"
      - "\\bIDEL\\b"
```

### Règle thématique

```yaml
thematic_rules:
  - tag: "réglementation"
    patterns:
      - "décret"
      - "arrêté"
```

Les patterns sont des **expressions régulières Python** (case-insensitive). Pour les thèmes, le matching se fait sur `titre + URL`. Pour les professions, sur le titre uniquement.

Aucun redémarrage nécessaire — les règles sont rechargées à chaque tag (cache LRU invalidé au restart).

---

## Architecture

```
sources.yaml          → liste des sources (RSS / HTML)
tagging_rules.yaml    → règles regex de tagging
veille.db             → SQLite (créé automatiquement)

app/
  main.py             → FastAPI routes + endpoints HTMX
  db.py               → SQLAlchemy engine + session
  models.py           → ORM : Source, Article
  fetcher.py          → collecte HTTP + déduplication SHA1
  tagger.py           → moteur de tagging (rules YAML)
  scheduler.py        → APScheduler (fetch toutes les 2h)
  source_loader.py    → upsert sources.yaml → DB
  parsers/
    rss.py            → feedparser
    html.py           → selectolax + CSS selectors
  templates/          → Jinja2 + HTMX + Tailwind CSS (CDN)
```

## Contraintes techniques

- **Rate limiting** : 1 requête/s max par domaine
- **User-Agent** : `InfoPara/1.0 (+contact: benoit.riquart@cgm.com)`
- **Déduplication** : hash SHA1 sur `(url_canonique | titre_normalisé)`
- **Stockage** : titre + extrait court uniquement (pas de contenu intégral)
- **Erreurs** : timeout, 404, 403 → loggés, champ `last_error` sur la source, pas de crash
