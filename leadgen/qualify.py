"""Qualification : transformer un contact en lead note de 0 a 100.

Un lead « qualifie », c'est une structure qui (a) traite des
donnees personnelles sensibles par metier, (b) a une taille ou le sujet remonte
a la direction, (c) expose une boite de fonction joignable.
"""

from __future__ import annotations

from .compliance import DOMAINES_GRAND_PUBLIC, classer_email

# Poids par tranche d'effectif INSEE : trop petit = pas de budget,
# trop gros = cycle de vente long et DSI interne.
POIDS_EFFECTIF = {
    "NN": 2, "00": 4, "01": 8, "02": 14, "03": 18,
    "11": 22, "12": 25, "21": 20, "22": 16,
    "31": 10, "32": 8, "41": 5, "42": 4, "51": 2, "52": 2, "53": 2,
}
POIDS_TYPE_EMAIL = {"generique": 30, "fonction": 26, "nominatif": 12, "technique": 0}

SEUIL_QUALIFIE = 55


def _poids_segment(priorite: int) -> int:
    return {5: 30, 4: 24, 3: 18, 2: 12, 1: 6}.get(priorite, 6)


def noter(
    entreprise,
    email: str,
    priorite_segment: int = 3,
    site_trouve: bool = True,
) -> tuple[int, list[str]]:
    """Retourne (score 0-100, raisons lisibles)."""
    score = 0
    raisons: list[str] = []

    poids = _poids_segment(priorite_segment)
    score += poids
    raisons.append(f"segment {entreprise.segment} (+{poids})")

    type_email = classer_email(email)
    poids = POIDS_TYPE_EMAIL.get(type_email, 0)
    score += poids
    raisons.append(f"email {type_email} (+{poids})")

    poids = POIDS_EFFECTIF.get(entreprise.tranche_effectif, 2)
    score += poids
    raisons.append(f"effectif {entreprise.tranche_effectif or 'NN'} (+{poids})")

    if site_trouve:
        score += 10
        raisons.append("site officiel verifie (+10)")

    _, _, domaine = email.partition("@")
    if domaine in DOMAINES_GRAND_PUBLIC:
        score -= 12
        raisons.append("boite grand public (-12)")

    if entreprise.date_creation and entreprise.date_creation[:4].isdigit():
        annee = int(entreprise.date_creation[:4])
        if annee <= 2023:
            score += 5
            raisons.append("structure etablie (+5)")

    score = max(0, min(100, score))
    return score, raisons


def est_qualifie(score: int, seuil: int = SEUIL_QUALIFIE) -> bool:
    return score >= seuil
