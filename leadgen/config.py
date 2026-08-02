"""Chargement du profil client ideal (config/icp.json)."""

from __future__ import annotations

import json
import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CHEMIN_ICP = RACINE / "config" / "icp.json"
CHEMIN_BASE = RACINE / "data" / "leads.db"
CHEMIN_OPPOSITION = RACINE / "data" / "liste-opposition.txt"
DOSSIER_EXPORTS = RACINE / "exports"

# Les secrets vivent hors du depot, dans le coffre commun du poste.
CHEMIN_SECRETS = RACINE.parent / "secrets" / "leadgen-brave.env"


def charger_secrets(chemin: Path | str = CHEMIN_SECRETS) -> list[str]:
    """Injecte les CLE=valeur du fichier dans l'environnement du process.

    Une variable deja definie dans l'environnement n'est jamais ecrasee.
    Retourne les noms charges (jamais les valeurs : rien dans les logs).
    """
    chemin = Path(chemin)
    if not chemin.exists():
        return []
    charges = []
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        cle, valeur = cle.strip(), valeur.strip().strip('"').strip("'")
        if cle and valeur and not os.environ.get(cle):
            os.environ[cle] = valeur
            charges.append(cle)
    return charges


class ICP:
    def __init__(self, donnees: dict):
        self.donnees = donnees
        self.segments = {s["cle"]: s for s in donnees.get("segments", [])}
        self.effectifs = list(donnees.get("effectifs_cibles", []))
        self.effectifs_libelles = donnees.get("effectifs_libelles", {})

    def segment(self, cle: str) -> dict:
        if cle not in self.segments:
            connus = ", ".join(sorted(self.segments))
            raise KeyError(f"segment inconnu : {cle} (disponibles : {connus})")
        return self.segments[cle]

    def priorite(self, cle: str) -> int:
        return int(self.segments.get(cle, {}).get("priorite", 3))

    def resoudre(self, demandes: list[str]) -> list[dict]:
        """'tous' ou liste de cles -> segments tries par priorite decroissante."""
        if not demandes or demandes == ["tous"]:
            choisis = list(self.segments.values())
        else:
            choisis = [self.segment(c) for c in demandes]
        return sorted(choisis, key=lambda s: -int(s.get("priorite", 3)))


def charger_icp(chemin: Path | str = CHEMIN_ICP) -> ICP:
    donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    return ICP(donnees)
