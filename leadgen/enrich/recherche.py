"""Trouver l'URL d'un site quand la devinette de domaine echoue.

Deux fournisseurs :
  - `devine`  : radicaux de domaine construits depuis la raison sociale.
                Aucun compte, aucune cle, mais taux de reussite faible sur les
                cabinets nommes d'apres leurs associes.
  - `brave`   : API officielle de Brave Search (offre gratuite : 2000 requetes
                par mois, cle a mettre dans la variable d'environnement
                BRAVE_API_KEY). C'est une API publique documentee, pas du
                scraping de moteur.

Dans les deux cas les URL ne sont que des CANDIDATES : `website.trouver_site`
verifie ensuite que la page parle bien de la structure.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

from .website import domaines_candidats

log = logging.getLogger("leadgen.recherche")

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
GOOGLE_URL = "https://www.googleapis.com/customsearch/v1"

# Annuaires, reseaux et agregateurs : jamais le site officiel d'un cabinet.
DOMAINES_AGREGATEURS = {
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "pagesjaunes.fr", "societe.com", "verif.com", "infogreffe.fr",
    "pappers.fr", "annuaire-entreprises.data.gouv.fr", "manageo.fr",
    "bilansgratuits.fr", "indeed.com", "glassdoor.fr", "yelp.fr", "mappy.com",
    "118712.fr", "justacote.com", "kompass.com", "leboncoin.fr", "wikipedia.org",
    "google.com", "bing.com", "doctolib.fr",
}


def _agregateur(url: str) -> bool:
    hote = urlparse(url).netloc.lower().removeprefix("www.")
    return any(hote == d or hote.endswith("." + d) for d in DOMAINES_AGREGATEURS)


def candidats_devines(entreprise, maximum: int = 12) -> list[str]:
    return domaines_candidats(entreprise.nom, maximum=maximum)


def candidats_brave(client, entreprise, cle: str | None = None,
                    maximum: int = 5) -> list[str]:
    """Interroge l'API Brave Search. Retourne [] si pas de cle ou en cas d'echec."""
    cle = cle or os.environ.get("BRAVE_API_KEY")
    if not cle:
        return []
    requete = " ".join(x for x in (entreprise.nom, entreprise.ville, "site officiel") if x)
    try:
        reponse = client.get(
            BRAVE_URL,
            params={"q": requete, "country": "fr", "search_lang": "fr", "count": 10},
            headers={"Accept": "application/json", "X-Subscription-Token": cle},
            timeout=20,
        )
        if reponse.status_code != 200:
            log.warning("Brave Search a repondu %s", reponse.status_code)
            return []
        donnees = reponse.json()
    except Exception as exc:
        log.warning("Brave Search indisponible (%s)", type(exc).__name__)
        return []

    return _racines((donnees.get("web") or {}).get("results", []), "url", maximum)


def _racines(resultats, champ: str, maximum: int) -> list[str]:
    """Domaines racines des resultats, agregateurs et reseaux ecartes."""
    urls: list[str] = []
    for resultat in resultats:
        url = resultat.get(champ) or ""
        if not url.startswith("http") or _agregateur(url):
            continue
        parts = urlparse(url)
        racine = f"{parts.scheme}://{parts.netloc}"
        if racine not in urls:
            urls.append(racine)
        if len(urls) >= maximum:
            break
    return urls


def candidats_google(client, entreprise, cle: str | None = None,
                     cx: str | None = None, maximum: int = 5) -> list[str]:
    """Google Programmable Search (JSON API) : 100 requetes par jour offertes.

    Deux identifiants a creer une fois :
      GOOGLE_API_KEY  - console.cloud.google.com, activer « Custom Search API »
      GOOGLE_CSE_ID   - programmablesearchengine.google.com, moteur regle sur
                        « rechercher sur tout le Web »
    """
    cle = cle or os.environ.get("GOOGLE_API_KEY")
    cx = cx or os.environ.get("GOOGLE_CSE_ID")
    if not cle or not cx:
        return []
    requete = " ".join(x for x in (entreprise.nom, entreprise.ville) if x)
    try:
        reponse = client.get(
            GOOGLE_URL,
            params={"key": cle, "cx": cx, "q": requete, "num": 10,
                    "gl": "fr", "hl": "fr"},
            timeout=20,
        )
        if reponse.status_code == 429:
            log.warning("Google Search : quota journalier atteint")
            return []
        if reponse.status_code != 200:
            log.warning("Google Search a repondu %s", reponse.status_code)
            return []
        donnees = reponse.json()
    except Exception as exc:
        log.warning("Google Search indisponible (%s)", type(exc).__name__)
        return []
    return _racines(donnees.get("items") or [], "link", maximum)


def candidats(client, entreprise, fournisseur: str = "devine") -> list[str]:
    """Liste d'URL a tester pour UN fournisseur donne.

    L'appelant enchaine les fournisseurs du moins cher au plus cher : la
    devinette est gratuite, le quota Brave est de 2000 requetes par mois.
    """
    if fournisseur == "brave":
        return candidats_brave(client, entreprise)
    if fournisseur == "google":
        return candidats_google(client, entreprise)
    if fournisseur == "aucun":
        return []
    return candidats_devines(entreprise)
