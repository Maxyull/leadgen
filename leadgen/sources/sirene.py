"""Source n.1 : l'annuaire des entreprises de l'Etat (base SIRENE, open data).

API publique, sans cle, sans compte : https://recherche-entreprises.api.gouv.fr
Licence ouverte Etalab. C'est la seule source « froide » utilisee : elle donne
la liste des structures d'un secteur, pas des contacts. Les contacts viennent
ensuite du site web public de chaque structure (module enrich/emails.py).

Note RGPD : la reponse contient un bloc `dirigeants` avec des noms de personnes
physiques. On ne le lit pas et on ne le stocke pas.
"""

from __future__ import annotations

import logging
import time
from typing import Iterator, Optional, Sequence

from ..models import Entreprise

log = logging.getLogger("leadgen.sirene")

BASE_URL = "https://recherche-entreprises.api.gouv.fr/search"
PAR_PAGE = 25          # maximum autorise par l'API
PAGES_MAX = 1000       # garde-fou
DELAI = 0.3            # l'API tolere ~7 req/s, on reste large en dessous


def _txt(valeur) -> str:
    return "" if valeur is None else str(valeur)


def parser_resultat(brut: dict, segment: str) -> Optional[Entreprise]:
    """Transforme un objet de l'API en Entreprise. None si inexploitable."""
    siren = _txt(brut.get("siren"))
    if not siren:
        return None
    siege = brut.get("siege") or {}
    if _txt(siege.get("etat_administratif")) == "F":
        return None
    if _txt(brut.get("date_fermeture")):
        return None
    nom = _txt(brut.get("nom_complet")) or _txt(brut.get("nom_raison_sociale"))
    return Entreprise(
        siren=siren,
        nom=nom.strip(),
        naf=_txt(brut.get("activite_principale")) or _txt(siege.get("activite_principale")),
        segment=segment,
        code_postal=_txt(siege.get("code_postal")),
        ville=_txt(siege.get("libelle_commune")),
        departement=_txt(siege.get("departement")),
        tranche_effectif=_txt(siege.get("tranche_effectif_salarie")),
        categorie=_txt(brut.get("categorie_entreprise")),
        date_creation=_txt(brut.get("date_creation")),
        adresse=_txt(siege.get("adresse")),
    )


def construire_params(
    naf: str,
    page: int,
    departement: str = "",
    region: str = "",
    effectifs: Sequence[str] = (),
    recherche_texte: str = "",
) -> dict:
    params = {
        "activite_principale": naf,
        "page": page,
        "per_page": PAR_PAGE,
        "etat_administratif": "A",
    }
    if recherche_texte:
        # meme code NAF pour avocats et notaires : seul le nom les distingue
        params["q"] = recherche_texte
    if departement:
        params["departement"] = departement
    if region:
        params["region"] = region
    if effectifs:
        params["tranche_effectif_salarie"] = ",".join(effectifs)
    return params


def rechercher(
    client,
    naf: str,
    segment: str,
    departement: str = "",
    region: str = "",
    effectifs: Sequence[str] = (),
    limite: int = 200,
    siege_strict: bool = True,
    delai: float = DELAI,
    recherche_texte: str = "",
) -> Iterator[Entreprise]:
    """Itere sur les entreprises d'un code NAF.

    `siege_strict` : ne garde que les structures dont le SIEGE est dans le
    departement demande. Sans ca l'API remonte les grands reseaux nationaux
    (FIDAL, FIDUCIAL...) des qu'ils ont une agence dans le departement.
    """
    obtenues = 0
    page = 1
    total_pages = None
    while obtenues < limite and page <= PAGES_MAX:
        params = construire_params(naf, page, departement, region, effectifs,
                                   recherche_texte)
        reponse = client.get(BASE_URL, params=params, timeout=30)
        if reponse.status_code == 429:
            log.warning("429 recu, pause 5 s")
            time.sleep(5)
            continue
        reponse.raise_for_status()
        data = reponse.json()
        if "erreur" in data:
            raise ValueError(f"API recherche-entreprises : {data['erreur'][:200]}")
        resultats = data.get("results") or []
        if total_pages is None:
            total_pages = data.get("total_pages") or 1
            log.info(
                "NAF %s (%s) : %s structures, %s pages",
                naf, segment, data.get("total_results"), total_pages,
            )
        for brut in resultats:
            entreprise = parser_resultat(brut, segment)
            if entreprise is None:
                continue
            if siege_strict and departement and entreprise.departement != departement:
                continue
            yield entreprise
            obtenues += 1
            if obtenues >= limite:
                return
        if not resultats or page >= total_pages:
            return
        page += 1
        if delai:
            time.sleep(delai)
