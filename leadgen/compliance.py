"""Garde-fous juridiques et techniques.

Regles appliquees (prospection B2B francaise, doctrine CNIL) :
  - on ne collecte que des adresses publiees publiquement sur le site de
    l'organisation, jamais derriere un login, jamais sur un reseau social ;
  - les adresses nominatives (prenom.nom@) sont ecartees par defaut : ce sont
    des donnees personnelles, on ne garde que les boites de fonction ;
  - robots.txt est respecte, une seule requete a la fois par domaine ;
  - toute adresse presente dans la liste d'opposition est bannie definitivement.
"""

from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
import urllib.robotparser
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

# Adresse email « raisonnable » : on reste volontairement strict pour eviter
# d'attraper des noms de fichiers (image@2x.png) ou des versions (v1.2@beta).
EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\b"
)

# Boites de fonction : la cible legitime de la prospection B2B.
LOCALPARTS_GENERIQUES = {
    "contact", "info", "infos", "information", "accueil", "bonjour", "hello",
    "cabinet", "etude", "secretariat", "secretaire", "administratif",
    "administration", "admin", "office", "mail", "courrier", "bureau",
}
LOCALPARTS_FONCTION = {
    "commercial", "commerciale", "direction", "directeur", "gerance", "gerant",
    "associes", "dpo", "rgpd", "juridique", "compta", "comptabilite",
    "facturation", "rh", "recrutement", "candidature", "candidatures",
    "partenariat", "partenariats", "presse", "communication", "marketing",
    "support", "si", "informatique", "dsi", "qualite", "conformite",
}
# Adresses techniques : jamais de prospection dessus (spamtraps, abuse desks).
LOCALPARTS_TECHNIQUES = {
    "noreply", "no-reply", "nepasrepondre", "ne-pas-repondre", "donotreply",
    "postmaster", "webmaster", "hostmaster", "abuse", "mailer-daemon",
    "bounce", "bounces", "root", "spam", "phishing", "security",
}

# Domaines a ne jamais prospecter (fournisseurs, exemples, plateformes).
DOMAINES_INTERDITS = {
    "example.com", "example.org", "example.net", "domain.com", "email.com",
    "sentry.io", "wixpress.com", "wordpress.com", "squarespace.com",
    "godaddy.com", "sentry.wixpress.com", "cloudflare.com", "google.com",
    "facebook.com", "linkedin.com", "twitter.com", "x.com", "instagram.com",
    # hebergeurs et plateformes : leur adresse trainait sur le site du client
    "ovh.com", "ovh.net", "ovhcloud.com", "ionos.fr", "1and1.fr", "o2switch.fr",
    "gandi.net", "infomaniak.com", "hostinger.com", "hostingersite.com",
    "shopify.com", "webflow.com", "jimdo.com", "sitew.com", "e-monsite.com",
}

# Boites grand public : l'adresse reste pro (un cabinet qui utilise gmail) mais
# elle est moins fiable, on la deprioritise dans le score.
DOMAINES_GRAND_PUBLIC = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.fr", "outlook.com",
    "outlook.fr", "live.fr", "live.com", "yahoo.fr", "yahoo.com", "orange.fr",
    "wanadoo.fr", "free.fr", "sfr.fr", "laposte.net", "bbox.fr", "numericable.fr",
    "aliceadsl.fr", "neuf.fr", "club-internet.fr", "icloud.com", "me.com",
}

# Messageries professionnelles de branche : une etude notariale utilise
# souvent office.x@notaires.fr plutot qu'une adresse sur son propre domaine.
DOMAINES_BRANCHE = {
    "notaires.fr", "avocat.fr", "avocats.fr", "avocat-conseil.fr",
    "experts-comptables.fr", "huissier-justice.fr", "commissaires-justice.fr",
    "chirurgiens-dentistes.fr", "medecin.fr", "adnov.fr",
}


def est_boite_connue(domaine: str) -> bool:
    """Le domaine est-il un fournisseur de messagerie identifiable ?

    Sert a ne PAS retenir une adresse hebergee sur un domaine technique
    (`...hostingersite.com`, plateforme de l'agence web) quand elle ne
    correspond pas au site de la structure.
    """
    domaine = (domaine or "").lower()
    connus = DOMAINES_GRAND_PUBLIC | DOMAINES_BRANCHE
    return any(domaine == d or domaine.endswith("." + d) for d in connus)


EXTENSIONS_FICHIERS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".ico",
    ".woff", ".woff2", ".ttf", ".pdf", ".mp4", ".webmanifest",
)

USER_AGENT_PAR_DEFAUT = (
    "LeadBot/1.0 (+https://exemple.fr ; prospection B2B ; "
    "desinscription : contact@exemple.fr)"
)


def user_agent() -> str:
    """Identite annoncee aux sites visites.

    Un robot doit etre identifiable et joignable : c'est ce qui permet a
    un webmaster de demander le retrait. La vraie valeur vient de
    l'environnement (`LEADGEN_USER_AGENT`, pose par le fichier de secrets
    local), jamais du code, qui reste generique.
    """
    return os.environ.get("LEADGEN_USER_AGENT", USER_AGENT_PAR_DEFAUT)


def normaliser_email(email: str) -> str:
    """Minuscules, espaces retires, formes obfusquees deja resolues en amont."""
    return email.strip().strip(".,;:<>()[]\"'").lower()


def _sans_accents(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn"
    )


def classer_email(email: str) -> str:
    """Retourne 'generique', 'fonction', 'technique' ou 'nominatif'."""
    email = normaliser_email(email)
    if "@" not in email:
        return "technique"
    local, _, domaine = email.partition("@")
    local_simple = _sans_accents(local)
    racine = re.split(r"[.\-_+]", local_simple)[0]

    if local_simple in LOCALPARTS_TECHNIQUES or racine in LOCALPARTS_TECHNIQUES:
        return "technique"
    if domaine in DOMAINES_INTERDITS:
        return "technique"
    if local_simple in LOCALPARTS_GENERIQUES:
        return "generique"
    if local_simple in LOCALPARTS_FONCTION:
        return "fonction"
    # contact.paris@, rh-lyon@, direction_generale@ restent des boites de fonction
    if racine in LOCALPARTS_GENERIQUES:
        return "generique"
    if racine in LOCALPARTS_FONCTION:
        return "fonction"
    return "nominatif"


def email_exploitable(email: str, autoriser_nominatif: bool = False) -> bool:
    """Filtre final avant stockage. Par defaut : boites de fonction seulement."""
    email = normaliser_email(email)
    if not EMAIL_RE.fullmatch(email):
        return False
    if email.endswith(EXTENSIONS_FICHIERS):
        return False
    _, _, domaine = email.partition("@")
    if any(domaine == d or domaine.endswith("." + d) for d in DOMAINES_INTERDITS):
        return False
    if domaine.endswith(".png") or domaine.endswith(".jpg"):
        return False
    type_email = classer_email(email)
    if type_email == "technique":
        return False
    if type_email == "nominatif" and not autoriser_nominatif:
        return False
    return True


class ListeOpposition:
    """Liste d'opposition (desinscriptions + exclusions manuelles).

    Fichier texte : une adresse ou un domaine (@exemple.fr) par ligne,
    les lignes commencant par # sont des commentaires.
    """

    def __init__(self, chemin: Path):
        self.chemin = Path(chemin)
        self.emails: set[str] = set()
        self.domaines: set[str] = set()
        self.recharger()

    def recharger(self) -> None:
        self.emails.clear()
        self.domaines.clear()
        if not self.chemin.exists():
            return
        for ligne in self.chemin.read_text(encoding="utf-8").splitlines():
            ligne = ligne.split("#", 1)[0].strip().lower()  # commentaire en fin de ligne
            if not ligne:
                continue
            if ligne.startswith("@"):
                self.domaines.add(ligne[1:])
            else:
                self.emails.add(normaliser_email(ligne))

    def contient(self, email: str) -> bool:
        email = normaliser_email(email)
        if email in self.emails:
            return True
        _, _, domaine = email.partition("@")
        return domaine in self.domaines

    def ajouter(self, email: str, motif: str = "desinscription") -> None:
        email = normaliser_email(email)
        if self.contient(email):
            return
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with self.chemin.open("a", encoding="utf-8") as f:
            f.write(f"{email}  # {motif}\n")
        self.emails.add(email)

    def filtrer(self, emails: Iterable[str]) -> list[str]:
        return [e for e in emails if not self.contient(e)]


class LimiteurDebit:
    """Un seul acces a la fois par domaine, avec delai minimum entre requetes."""

    def __init__(self, delai: float = 1.5):
        self.delai = delai
        self._dernier: dict[str, float] = {}
        self._verrou = threading.Lock()

    def attendre(self, url: str) -> None:
        domaine = urlparse(url).netloc.lower()
        with self._verrou:
            precedent = self._dernier.get(domaine, 0.0)
            reste = self.delai - (time.monotonic() - precedent)
            if reste > 0:
                time.sleep(reste)
            self._dernier[domaine] = time.monotonic()


class CacheRobots:
    """Cache de robots.txt. En cas d'erreur reseau on considere le site permis
    (comportement des crawlers courants), sauf 401/403 qui interdisent tout."""

    def __init__(self, fetch=None, actif: bool = True):
        self.actif = actif
        self._fetch = fetch
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _charger(self, base: str):
        if base in self._cache:
            return self._cache[base]
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(base + "/robots.txt")
        try:
            if self._fetch is None:
                parser.read()
            else:
                contenu = self._fetch(base + "/robots.txt")
                parser.parse((contenu or "").splitlines())
        except Exception:
            parser = None
        self._cache[base] = parser
        return parser

    def autorise(self, url: str) -> bool:
        if not self.actif:
            return True
        parts = urlparse(url)
        if not parts.scheme or not parts.netloc:
            return False
        base = f"{parts.scheme}://{parts.netloc}"
        parser = self._charger(base)
        if parser is None:
            return True
        try:
            return parser.can_fetch(user_agent(), url)
        except Exception:
            return True
