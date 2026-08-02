"""Codes geographiques INSEE utilises par les deux sources."""

from __future__ import annotations

# 101 departements (metropole + DOM).
DEPARTEMENTS: list[str] = (
    [f"{n:02d}" for n in range(1, 20)]
    + ["2A", "2B"]
    + [f"{n:02d}" for n in range(21, 96)]
    + ["971", "972", "973", "974", "976"]
)

# Regions INSEE : 18 requetes Overpass au lieu de 101, service benevole oblige.
REGIONS: dict[str, str] = {
    "84": "Auvergne-Rhone-Alpes",
    "27": "Bourgogne-Franche-Comte",
    "53": "Bretagne",
    "24": "Centre-Val de Loire",
    "94": "Corse",
    "44": "Grand Est",
    "32": "Hauts-de-France",
    "11": "Ile-de-France",
    "28": "Normandie",
    "75": "Nouvelle-Aquitaine",
    "76": "Occitanie",
    "52": "Pays de la Loire",
    "93": "Provence-Alpes-Cote d'Azur",
    "01": "Guadeloupe",
    "02": "Martinique",
    "03": "Guyane",
    "04": "La Reunion",
    "06": "Mayotte",
}


def resoudre_departements(demandes: list[str]) -> list[str]:
    """'tous' / 'france' -> les 101 departements ; sinon la liste telle quelle."""
    if not demandes:
        return []
    if len(demandes) == 1 and demandes[0].lower() in ("tous", "toutes", "france"):
        return list(DEPARTEMENTS)
    return demandes


def zones_osm(departements: list[str]) -> tuple[list[str], str]:
    """Choisit la maille Overpass : au-dela de 20 departements on interroge par
    region (18 requetes au lieu de 101) - Overpass est un service benevole."""
    if len(departements) > 20:
        return list(REGIONS), "region"
    return departements, "departement"
