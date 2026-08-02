"""Source n.2 : OpenStreetMap via l'API Overpass.

Interet : les cabinets cartographies portent souvent directement les tags
`website` et `email` - c'est-a-dire l'information que la base SIRENE n'a pas.
Donnees sous licence ODbL, reutilisation libre avec attribution
(« (c) les contributeurs OpenStreetMap »).

Overpass est un service benevole mutualise : une requete par segment et par
departement, jamais en boucle serree.
"""

from __future__ import annotations

import logging
import time
from typing import Iterator, Sequence

from ..compliance import normaliser_email
from ..models import Entreprise

log = logging.getLogger("leadgen.osm")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DELAI = 8.0          # entre deux requetes Overpass (service benevole : on reste poli)
ESSAIS = 3           # Overpass repond souvent 429/504 : on retente au lieu d'abandonner
ATTENTE_RETRY = 30.0  # secondes, multipliees par le numero de tentative


# admin_level francais : 4 = region, 6 = departement.
NIVEAUX = {"region": "4", "departement": "6"}


def construire_requete(tags: Sequence[str], zone: str, niveau: str = "departement",
                       timeout: int = 120) -> str:
    """Requete Overpass QL sur un departement (85) ou une region INSEE (52)."""
    if not tags:
        raise ValueError("aucun tag OSM pour ce segment")
    if not zone:
        raise ValueError("Overpass exige une zone (ex: 85 pour la Vendee)")
    if niveau not in NIVEAUX:
        raise ValueError(f"niveau inconnu : {niveau}")
    filtres = []
    for tag in tags:
        cle, _, valeur = tag.partition("=")
        filtres.append(f'  nwr["{cle}"="{valeur}"](area.zone);')
    corps = "\n".join(filtres)
    return (
        f"[out:json][timeout:{timeout}];\n"
        f'area["ref:INSEE"="{zone}"]["admin_level"="{NIVEAUX[niveau]}"]->.zone;\n'
        f"(\n{corps}\n);\n"
        f"out center tags;"
    )


def _tag(tags: dict, *cles: str) -> str:
    for cle in cles:
        valeur = tags.get(cle)
        if valeur:
            return str(valeur).strip()
    return ""


def parser_element(element: dict, segment: str, departement: str = "") -> Entreprise | None:
    tags = element.get("tags") or {}
    nom = _tag(tags, "name", "operator", "brand")
    if not nom:
        return None
    identifiant = f"osm:{element.get('type', 'node')}/{element.get('id')}"
    site = _tag(tags, "website", "contact:website", "url")
    if site and not site.startswith("http"):
        site = "https://" + site.lstrip("/")
    email = normaliser_email(_tag(tags, "email", "contact:email"))
    code_postal = _tag(tags, "addr:postcode")
    return Entreprise(
        siren=identifiant,
        nom=nom,
        naf="",
        segment=segment,
        code_postal=code_postal,
        ville=_tag(tags, "addr:city"),
        departement=departement or code_postal[:2],
        tranche_effectif="",
        categorie="",
        date_creation="",
        adresse=" ".join(x for x in (_tag(tags, "addr:housenumber"),
                                     _tag(tags, "addr:street"),
                                     code_postal, _tag(tags, "addr:city")) if x),
        site=site or None,
        site_statut="trouve" if site else "inconnu",
        email_public=email,
        source="osm",
    )


def rechercher(
    client,
    tags: Sequence[str],
    segment: str,
    zone: str,
    limite: int = 500,
    delai: float = DELAI,
    niveau: str = "departement",
) -> Iterator[Entreprise]:
    requete = construire_requete(tags, zone, niveau)
    reponse = None
    for essai in range(ESSAIS):
        reponse = client.post(OVERPASS_URL, data={"data": requete}, timeout=180)
        if reponse.status_code not in (429, 504):
            break
        # 429 = creneau occupe, 504 = requete trop lourde a cet instant.
        # Overpass demande explicitement d'attendre avant de reessayer.
        if essai < ESSAIS - 1:
            attente = ATTENTE_RETRY * (essai + 1)
            log.info("Overpass occupe (%s) sur %s %s, nouvelle tentative dans %ds",
                     reponse.status_code, niveau, zone, attente)
            time.sleep(attente)
    if reponse is None or reponse.status_code in (429, 504):
        log.warning("Overpass indisponible pour %s %s apres %d tentatives, on passe",
                    niveau, zone, ESSAIS)
        return
    reponse.raise_for_status()
    elements = (reponse.json() or {}).get("elements", [])
    log.info("OSM %s %s %s : %d objets", segment, niveau, zone, len(elements))
    departement = zone if niveau == "departement" else ""
    rendus = 0
    for element in elements:
        entreprise = parser_element(element, segment, departement)
        if entreprise is None:
            continue
        yield entreprise
        rendus += 1
        if rendus >= limite:
            break
    if delai:
        time.sleep(delai)
