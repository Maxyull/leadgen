"""Doublures HTTP : aucun test ne sort sur le reseau."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leadgen.models import Entreprise  # noqa: E402


class FausseReponse:
    def __init__(self, url: str, texte: str = "", status: int = 200, donnees=None):
        self.url = url
        self.text = texte
        self.status_code = status
        self._donnees = donnees

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} sur {self.url}")

    def json(self):
        if self._donnees is not None:
            return self._donnees
        return json.loads(self.text)


class FauxClient:
    """Sert un dictionnaire {url: html}. Tout le reste repond 404.

    `appels` garde la trace des URL demandees (utile pour verifier qu'on ne
    visite pas 50 pages par site).
    """

    def __init__(self, pages: dict[str, str] | None = None, api=None,
                 injoignables=(), overpass=None):
        self.pages = pages or {}
        self.api = api          # callable(params) -> dict, pour l'API SIRENE
        self.overpass = overpass  # callable(requete) -> dict, pour Overpass
        self.injoignables = set(injoignables)
        self.appels: list[str] = []

    def post(self, url, data=None, **kwargs):
        self.appels.append(url)
        if self.overpass is None:
            return FausseReponse(url, texte="", status=404)
        resultat = self.overpass((data or {}).get("data", ""))
        if isinstance(resultat, int):        # le fournisseur simule un code HTTP
            return FausseReponse(url, status=resultat, donnees={})
        return FausseReponse(url, donnees=resultat)

    def get(self, url, params=None, **kwargs):
        self.appels.append(url)
        if params is not None and self.api is not None:
            return FausseReponse(url, donnees=self.api(params))
        if url in self.injoignables:
            raise ConnectionError(f"{url} injoignable")
        cle = url.rstrip("/") if url.rstrip("/") in self.pages else url
        if cle in self.pages:
            return FausseReponse(url, texte=self.pages[cle])
        return FausseReponse(url, texte="", status=404)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class RobotsPermissif:
    def autorise(self, url: str) -> bool:
        return True


class RobotsInterdit:
    def __init__(self, motif: str):
        self.motif = motif

    def autorise(self, url: str) -> bool:
        return self.motif not in url


class LimiteurNul:
    """Pas d'attente pendant les tests."""

    def attendre(self, url: str) -> None:
        return None


@pytest.fixture
def robots():
    return RobotsPermissif()


@pytest.fixture
def limiteur():
    return LimiteurNul()


@pytest.fixture
def entreprise_avocats():
    return Entreprise(
        siren="111111111",
        nom="CABINET DUPONT AVOCATS",
        naf="69.10Z",
        segment="avocats",
        code_postal="85000",
        ville="LA ROCHE-SUR-YON",
        departement="85",
        tranche_effectif="12",
        categorie="PME",
        date_creation="2015-03-01",
        adresse="12 RUE DES HALLES 85000 LA ROCHE-SUR-YON",
    )
