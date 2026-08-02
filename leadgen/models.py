"""Modeles de donnees partages par tout le pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Entreprise:
    """Une entreprise issue de la base publique SIRENE (open data)."""

    siren: str
    nom: str
    naf: str
    segment: str
    code_postal: str = ""
    ville: str = ""
    departement: str = ""
    tranche_effectif: str = ""
    categorie: str = ""
    date_creation: str = ""
    adresse: str = ""
    site: Optional[str] = None
    site_statut: str = "inconnu"  # inconnu | trouve | introuvable | bloque
    email_public: str = ""        # deja publie par la source (cas OpenStreetMap)
    source: str = "sirene"        # sirene | osm

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Lead:
    """Un contact professionnel exploitable pour la prospection B2B."""

    siren: str
    nom: str
    segment: str
    email: str
    type_email: str  # generique | fonction | nominatif | technique
    site: str = ""
    source_url: str = ""
    ville: str = ""
    code_postal: str = ""
    departement: str = ""
    tranche_effectif: str = ""
    naf: str = ""
    source: str = "sirene"   # d'ou vient la donnee (registre RGPD)
    titre: str = ""          # titre du site, pour le mail
    accroche: str = ""       # ce que la structure dit d'elle-meme
    signaux: str = ""        # mots-cles releves (ia, rgpd, paie...)
    angle: str = ""          # angle d'accroche suggere
    score: int = 0
    raisons: list = field(default_factory=list)
    statut: str = "nouveau"  # nouveau | exporte | desinscrit | rejete

    def to_dict(self) -> dict:
        d = asdict(self)
        d["raisons"] = " | ".join(self.raisons)
        return d
