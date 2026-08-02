"""Accroches de personnalisation prises sur le site de la structure.

L'objectif n'est pas de profiler qui que ce soit : on releve ce que la
structure dit publiquement d'elle-meme sur sa page d'accueil, pour que le mail
parle de SON metier plutot que d'un argumentaire generique.

Le signal le plus fort : un cabinet qui parle deja d'IA sur son
site a le probleme, il ne reste qu'a le nommer.
"""

from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

# signal -> expressions qui le declenchent (texte sans accents, minuscules)
SIGNAUX = {
    "ia": ("intelligence artificielle", "chatgpt", " ia ", "copilot", "llm",
           "generative", "openai", "mistral ai"),
    "rgpd": ("rgpd", "donnees personnelles", "protection des donnees", "cnil", "dpo"),
    "confidentialite": ("secret professionnel", "confidentialite", "secret medical"),
    "cybersecurite": ("cybersecurite", "cyberattaque", "securite informatique"),
    "droit-social": ("droit du travail", "droit social", "prud'hom", "licenciement"),
    "droit-affaires": ("droit des affaires", "droit des societes", "fusion", "cession"),
    "famille-succession": ("succession", "divorce", "droit de la famille", "donation"),
    "paie": ("bulletins de paie", "fiche de paie", "gestion de la paie", "paie"),
    "fiscalite": ("fiscalite", "fiscal", "liasse", "declaration d'impots"),
    "audit": ("commissariat aux comptes", "audit legal", "expertise judiciaire"),
    "immobilier": ("droit immobilier", "bail", "copropriete", "urbanisme"),
    "sante": ("droit de la sante", "dossier patient", "donnees de sante"),
}

MAX_ACCROCHE = 180


def _normaliser(texte: str) -> str:
    texte = "".join(
        c for c in unicodedata.normalize("NFD", texte or "")
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", texte).lower()


def _nettoyer(texte: str, maximum: int = MAX_ACCROCHE) -> str:
    texte = re.sub(r"\s+", " ", (texte or "")).strip()
    if len(texte) <= maximum:
        return texte
    coupe = texte[:maximum].rsplit(" ", 1)[0]
    return coupe + "..."


def analyser(html: str) -> dict:
    """Retourne {titre, accroche, signaux} pour une page d'accueil."""
    soup = BeautifulSoup(html or "", "lxml")

    titre = ""
    if soup.title and soup.title.string:
        titre = _nettoyer(soup.title.string, 90)
    if not titre and soup.h1:
        titre = _nettoyer(soup.h1.get_text(" "), 90)

    accroche = ""
    for selecteur, attribut in (
        ('meta[name="description"]', "content"),
        ('meta[property="og:description"]', "content"),
    ):
        balise = soup.select_one(selecteur)
        if balise and balise.get(attribut):
            accroche = _nettoyer(balise[attribut])
            break
    if not accroche:
        premier = soup.find("p")
        if premier:
            accroche = _nettoyer(premier.get_text(" "))

    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    texte = _normaliser(soup.get_text(" ", strip=True))
    trouves = [cle for cle, motifs in SIGNAUX.items()
               if any(motif in texte for motif in motifs)]

    return {"titre": titre, "accroche": accroche, "signaux": trouves}


def accroche_mail(analyse: dict) -> str:
    """Une phrase d'angle pour le mail, deduite des signaux (la plus forte
    d'abord). Vide si le site ne dit rien d'exploitable."""
    signaux = set(analyse.get("signaux") or ())
    if "ia" in signaux and "rgpd" in signaux:
        return "parle deja d'IA ET de RGPD : angle direct, ils ont le probleme"
    if "ia" in signaux:
        return "parle d'IA sur son site : demander comment ils protegent les donnees"
    if "rgpd" in signaux or "confidentialite" in signaux:
        return "met en avant la confidentialite : angle conformite"
    if "sante" in signaux:
        return "donnees de sante (article 9) : angle risque maximal"
    if "paie" in signaux:
        return "traite la paie : identites, RIB, salaires"
    if "famille-succession" in signaux:
        return "successions et famille : dossiers tres nominatifs"
    if "droit-social" in signaux:
        return "droit social : dossiers salaries nominatifs"
    return ""
