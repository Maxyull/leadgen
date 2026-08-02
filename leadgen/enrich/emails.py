"""Extraction des boites de contact publiees sur le site officiel.

On ne visite que quelques pages evidentes (accueil, contact, mentions legales)
et uniquement si robots.txt l'autorise. Les adresses obfusquees courantes
(« nom [at] domaine [dot] fr ») sont reconstituees : elles restent publiees
volontairement, l'obfuscation vise les robots de spam, pas la lecture humaine.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import signaux as mod_signaux
from ..compliance import (
    EMAIL_RE,
    user_agent,
    classer_email,
    email_exploitable,
    est_boite_connue,
    normaliser_email,
)

log = logging.getLogger("leadgen.emails")

# Pages ou les cabinets francais publient leur adresse de contact.
CHEMINS_CONTACT = (
    "",
    "/contact",
    "/contact.html",
    "/contactez-nous",
    "/nous-contacter",
    "/mentions-legales",
    "/mentions-legales.html",
    "/informations-legales",
    "/le-cabinet",
    "/a-propos",
    "/equipe",
)

# nom (at) domaine (dot) fr  /  nom [arobase] domaine [point] fr  /  nom AT domaine
_AT = r"(?:\(\s*(?:at|@|arobase|chez)\s*\)|\[\s*(?:at|@|arobase|chez)\s*\]|\s+(?:at|arobase|chez)\s+)"
_DOT = r"(?:\(\s*(?:dot|point|\.)\s*\)|\[\s*(?:dot|point|\.)\s*\]|\s+(?:dot|point)\s+)"
RE_OBFUSQUE = re.compile(
    rf"([A-Za-z0-9._%+-]+)\s*{_AT}\s*"
    rf"((?:[A-Za-z0-9-]+\s*(?:{_DOT}|\.)\s*)+[A-Za-z]{{2,}})",
    re.IGNORECASE,
)


def desobfusquer(texte: str) -> str:
    """Remplace les formes « a (at) b (dot) c » par « a@b.c »."""
    def _remplacer(m: re.Match) -> str:
        gauche = m.group(1)
        droite = re.sub(_DOT, ".", m.group(2), flags=re.IGNORECASE)
        droite = re.sub(r"\s+", "", droite)
        return f"{gauche}@{droite}"

    return RE_OBFUSQUE.sub(_remplacer, texte)


def extraire_emails(html: str) -> list[str]:
    """Toutes les adresses d'une page : liens mailto + texte visible."""
    trouves: list[str] = []
    vus: set[str] = set()

    soup = BeautifulSoup(html or "", "lxml")
    for balise in soup.select("a[href^='mailto:']"):
        brut = (balise.get("href") or "")[7:].split("?")[0]
        email = normaliser_email(brut)
        if email and email not in vus:
            vus.add(email)
            trouves.append(email)

    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    texte = desobfusquer(soup.get_text(" ", strip=True))
    for m in EMAIL_RE.finditer(texte):
        email = normaliser_email(m.group(0))
        if email and email not in vus:
            vus.add(email)
            trouves.append(email)
    return trouves


# Mots qui, dans un lien, annoncent une page portant des coordonnees.
MOTS_LIENS = (
    "contact", "joindre", "coordonnee", "mentions", "legal", "cabinet",
    "equipe", "propos", "etude", "office", "notaire", "qui-sommes",
)


def _sans_accents(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte or "")
        if unicodedata.category(c) != "Mn"
    )


def liens_utiles(html: str, url_base: str, maximum: int = 6) -> list[str]:
    """Liens INTERNES de la page qui mènent probablement aux coordonnees.

    Beaucoup plus fiable que deviner des chemins : un cabinet sur trois
    utilise /nous-joindre, /coordonnees ou une page enfant.
    """
    soup = BeautifulSoup(html or "", "lxml")
    hote = urlparse(url_base).netloc.lower().removeprefix("www.")
    trouves: list[str] = []
    for balise in soup.select("a[href]"):
        href = (balise.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        url = urljoin(url_base, href).split("#")[0]
        parts = urlparse(url)
        if parts.scheme not in ("http", "https"):
            continue
        if parts.netloc.lower().removeprefix("www.") != hote:
            continue
        cible = _sans_accents(href + " " + balise.get_text(" ", strip=True)).lower()
        if any(mot in cible for mot in MOTS_LIENS) and url not in trouves:
            trouves.append(url)
            if len(trouves) >= maximum:
                break
    return trouves


def _dossier(url: str) -> str:
    """URL du repertoire contenant la page (toujours terminee par /)."""
    parts = urlparse(url)
    chemin = parts.path if parts.path.endswith("/") else parts.path.rsplit("/", 1)[0] + "/"
    return f"{parts.scheme}://{parts.netloc}{chemin or '/'}"


def _meme_domaine(email: str, site: str) -> bool:
    hote = urlparse(site).netloc.lower().removeprefix("www.")
    _, _, domaine = email.partition("@")
    return bool(hote) and (domaine == hote or domaine.endswith("." + hote)
                           or hote.endswith("." + domaine))


class RecolteSite:
    """Ce qu'on ramene d'un site : les adresses et de quoi personnaliser."""

    def __init__(self, emails=None, analyse=None):
        self.emails: list[tuple[str, str]] = emails or []
        self.analyse: dict = analyse or {"titre": "", "accroche": "", "signaux": []}

    def __iter__(self):
        return iter(self.emails)

    def __len__(self):
        return len(self.emails)


def collecter_emails(
    client,
    site: str,
    robots,
    limiteur,
    autoriser_nominatif: bool = False,
    chemins=CHEMINS_CONTACT,
    max_pages: int = 5,
) -> RecolteSite:
    """Adresses + accroches de personnalisation pour un site, dedoublonnees.

    Priorite aux adresses hebergees sur le domaine du site : une adresse
    trouvee sur un site mais appartenant a un prestataire (l'agence web qui
    signe le pied de page) n'est pas un lead.
    """
    resultats: list[tuple[str, str]] = []
    vus: set[str] = set()
    visitees = 0
    analyse = None

    racine = site if site.endswith("/") else site + "/"
    file = [urljoin(racine, chemin.lstrip("/")) for chemin in chemins]
    demandees: set[str] = set()
    index = 0

    while index < len(file):
        url = file[index]
        index += 1
        if visitees >= max_pages:
            break
        if url in demandees or not robots.autorise(url):
            continue
        demandees.add(url)
        limiteur.attendre(url)
        try:
            reponse = client.get(
                url, timeout=6, follow_redirects=True,
                headers={"User-Agent": user_agent()},
            )
        except Exception as exc:
            log.debug("%s injoignable (%s)", url, type(exc).__name__)
            continue
        if reponse.status_code >= 400:
            continue
        visitees += 1
        if analyse is None:      # la premiere page atteinte fait office d'accueil
            analyse = mod_signaux.analyser(reponse.text or "")
            # On repart de l'URL finale : si le site redirige www -> nu, garder
            # l'URL d'origine ferait payer une redirection a chaque page.
            finale = str(reponse.url)
            file[index:] = [urljoin(_dossier(finale), c.lstrip("/"))
                            for c in chemins if c]
            # Les vrais liens de la page priment sur les chemins devines :
            # beaucoup de sites utilisent /nous-joindre, /coordonnees, etc.
            liens = liens_utiles(reponse.text or "", finale)
            file[index:index] = [u for u in liens if u not in demandees]
        for email in extraire_emails(reponse.text or ""):
            if email in vus:
                continue
            vus.add(email)
            if not email_exploitable(email, autoriser_nominatif):
                continue
            resultats.append((email, str(reponse.url)))

        # Une boite generique sur le bon domaine : inutile de continuer a
        # frapper 8 URL de plus, c'est deja le meilleur contact possible.
        if any(classer_email(e) == "generique" and _meme_domaine(e, site)
               for e, _ in resultats):
            break

    propres = [t for t in resultats if _meme_domaine(t[0], site)]
    # Sinon on n'accepte qu'une messagerie identifiable (gmail, notaires.fr...).
    # Une adresse sur un domaine technique d'hebergeur n'est pas un contact.
    retenus = propres or [t for t in resultats
                          if est_boite_connue(t[0].partition("@")[2])]
    ordre = {"generique": 0, "fonction": 1, "nominatif": 2, "technique": 3}
    retenus.sort(key=lambda t: ordre.get(classer_email(t[0]), 9))
    return RecolteSite(retenus, analyse)
