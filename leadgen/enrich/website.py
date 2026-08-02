"""Retrouver le site officiel d'une structure sans passer par un moteur.

Methode : on genere des noms de domaine plausibles a partir de la raison
sociale, on teste ceux qui repondent, puis on VERIFIE que la page parle bien
de la structure (jetons du nom, code postal, ville ou SIREN presents).
Sans verification on ramasse des domaines parking et des homonymes.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Iterable, Optional

from ..compliance import user_agent

log = logging.getLogger("leadgen.website")

# Formes juridiques et mots outils : jamais dans un nom de domaine.
MOTS_STRUCTURE = {
    "sarl", "sas", "sasu", "sa", "scp", "selarl", "selarlu", "selas", "selafa",
    "sci", "snc", "eurl", "scm", "gie", "scop", "eirl", "sepv", "sasp",
    "societe", "association", "et", "de", "du", "des", "la", "le", "les",
    "l", "d", "au", "aux", "en", "sur", "aux",
}
# Mots de metier : utiles dans un nom de domaine (dupont-avocats.fr) mais
# inutilisables pour confirmer qu'une page parle bien de CETTE structure.
MOTS_GENERIQUES = {
    "cabinet", "groupe", "group", "conseil", "conseils", "associes", "associe",
    "avocat", "avocats", "expertise", "comptable", "comptables", "etude",
    "etudes", "notaire", "notaires", "notarial", "notariale", "office",
    "france", "consulting", "partners", "gestion", "juridique", "juridiques",
    "audit", "expert", "experts", "patrimoine", "assurance", "assurances",
    "immobilier", "solutions", "services", "maitre",
}
MOTS_VIDES = MOTS_STRUCTURE | MOTS_GENERIQUES
TLDS = (".fr", ".com", ".net", ".eu")
PREFIXES = ("cabinet-",)  # variantes testees en dernier recours


def _sans_accents(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn"
    )


def jetons(nom: str) -> list[str]:
    """Mots utilisables dans un nom de domaine (formes juridiques retirees)."""
    nom = _sans_accents(nom).lower()
    nom = re.sub(r"\(.*?\)", " ", nom)          # (SIGLE ; AUTRE NOM)
    bruts = re.split(r"[^a-z0-9]+", nom)
    return [m for m in bruts if len(m) > 1 and m not in MOTS_STRUCTURE]


def jetons_forts(nom: str) -> list[str]:
    """Mots qui identifient vraiment la structure (metier retire)."""
    return [m for m in jetons(nom) if m not in MOTS_GENERIQUES]


def slugs_candidats(nom: str) -> list[str]:
    """Radicaux de domaine plausibles, du plus probable au moins probable."""
    tous = jetons(nom)
    forts = jetons_forts(nom)
    if not tous:
        return []
    propositions = ["".join(forts), "-".join(forts)]
    if tous and tous[0] in MOTS_GENERIQUES and len(tous) > 1:
        # « CABINET DUPONT AVOCATS » -> dupont-avocats.fr
        propositions += ["-".join(tous[1:]), "".join(tous[1:])]
    propositions += [
        "".join(tous), "-".join(tous),
        "-".join(tous[:2]), "".join(tous[:2]),
    ]
    candidats: list[str] = []
    for slug in propositions:
        if 3 <= len(slug) <= 40 and slug not in candidats:
            candidats.append(slug)
    return candidats


def domaines_candidats(nom: str, maximum: int = 12) -> list[str]:
    """Ordre de test : tous les radicaux en .fr, puis les autres extensions,
    puis les variantes prefixees (cabinet-...)."""
    slugs = slugs_candidats(nom)
    urls: list[str] = []
    for tld in TLDS:
        for slug in slugs:
            urls.append(f"https://{slug}{tld}")
    for prefixe in PREFIXES:
        for slug in slugs:
            urls.append(f"https://{prefixe}{slug}.fr")
    uniques: list[str] = []
    for url in urls:
        if url not in uniques:
            uniques.append(url)
    return uniques[:maximum]


def page_correspond(html: str, nom: str, code_postal: str = "", ville: str = "",
                    siren: str = "") -> bool:
    """Le contenu confirme-t-il qu'on est bien chez cette structure ?"""
    if not html:
        return False
    texte = _sans_accents(html).lower()
    if siren:
        compact = re.sub(r"[^0-9]", "", texte)
        if siren in compact:
            return True
    forts = [m for m in jetons_forts(nom) if len(m) >= 4]
    if not forts:
        return False
    trouves = sum(1 for m in forts if m in texte)
    if trouves == 0:
        return False
    if trouves >= 2:
        return True
    # Un seul mot en commun : trop faible (« Dupont avocats » vs « Dupont
    # traiteur »). On exige alors un indice de localisation.
    if not (code_postal or ville):
        return True
    return bool(
        (code_postal and code_postal in texte)
        or (ville and _sans_accents(ville).lower() in texte)
    )


def trouver_site(
    client,
    entreprise,
    robots,
    limiteur,
    candidats: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Retourne l'URL du site officiel, ou None."""
    urls = list(candidats) if candidats is not None else domaines_candidats(entreprise.nom)
    for url in urls:
        if not robots.autorise(url):
            log.debug("robots.txt interdit %s", url)
            continue
        limiteur.attendre(url)
        try:
            reponse = client.get(
                url, timeout=6, follow_redirects=True,
                headers={"User-Agent": user_agent()},
            )
        except Exception as exc:  # DNS inexistant, TLS invalide, timeout
            log.debug("%s injoignable (%s)", url, type(exc).__name__)
            continue
        if reponse.status_code >= 400:
            continue
        html = reponse.text or ""
        if page_correspond(html, entreprise.nom, entreprise.code_postal,
                           entreprise.ville, entreprise.siren):
            final = str(reponse.url)
            log.info("site trouve pour %s : %s", entreprise.nom[:40], final)
            return final
    return None
