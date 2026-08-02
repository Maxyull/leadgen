"""Regression : le pipeline complet (collecte -> enrichissement -> export)
doit produire exactement le fichier de reference tests/golden/leads_attendus.csv.

Aucun acces reseau : l'API SIRENE et les sites web sont simules. Si un score,
un filtre ou une colonne change, ce test casse - c'est le but.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from conftest import FauxClient

from leadgen import cli
from leadgen.config import CHEMIN_ICP

GOLDEN = Path(__file__).parent / "golden" / "leads_attendus.csv"

# --- structures renvoyees par la fausse API SIRENE -------------------------
def _entreprise_api(siren, nom, naf, cp, ville, effectif, creation):
    return {
        "siren": siren,
        "nom_complet": nom,
        "activite_principale": naf,
        "categorie_entreprise": "PME",
        "date_creation": creation,
        "date_fermeture": None,
        "dirigeants": [{"nom": "PRIVE", "prenoms": "PERSONNE"}],
        "siege": {
            "code_postal": cp, "libelle_commune": ville, "departement": "85",
            "tranche_effectif_salarie": effectif, "etat_administratif": "A",
            "adresse": f"1 RUE DU TEST {cp} {ville}", "activite_principale": naf,
        },
    }


PAR_NAF = {
    "69.10Z": [
        _entreprise_api("111111111", "CABINET DUPONT AVOCATS", "69.10Z",
                        "85000", "LA ROCHE-SUR-YON", "12", "2015-03-01"),
        _entreprise_api("444444444", "CABINET INVISIBLE CONSEIL", "69.10Z",
                        "85200", "FONTENAY-LE-COMTE", "02", "2018-01-01"),
    ],
    "69.20Z": [
        _entreprise_api("222222222", "SCP MARTIN EXPERTISE COMPTABLE", "69.20Z",
                        "85300", "CHALLANS", "02", "2019-06-01"),
    ],
    "62.02A": [
        _entreprise_api("333333333", "GAMMA SOLUTIONS", "62.02A",
                        "85100", "LES SABLES-D'OLONNE", "01", "2024-02-01"),
    ],
}

# --- sites web simules ----------------------------------------------------
ACCUEIL_DUPONT = """<html><head><title>Cabinet Dupont Avocats - La Roche-sur-Yon</title>
<meta name="description" content="Droit des affaires, contentieux et conseil aux entreprises en Vendee.">
</head><body><h1>Cabinet Dupont Avocats</h1>
<p>Droit des affaires a La Roche-sur-Yon (85000).</p>
<p>Nous utilisons l'intelligence artificielle pour accelerer la redaction des actes.</p>
</body></html>"""
CONTACT_DUPONT = """<html><body><h1>Contact - Cabinet Dupont</h1>
<a href="mailto:contact@dupont-avocats.fr">Nous ecrire</a>
<p>Delegue a la protection des donnees : dpo@dupont-avocats.fr</p>
<p>Me Jean Dupont : jean.dupont@dupont-avocats.fr</p>
<p>Ne pas repondre : noreply@dupont-avocats.fr</p>
<footer>Site par contact@agence-web.com</footer></body></html>"""

ACCUEIL_MARTIN = """<html><body><h1>SCP Martin - experts-comptables</h1>
<p>Gestion de la paie et fiscalite a Challans (85300).</p></body></html>"""
CONTACT_MARTIN = """<html><body><p>Martin : cabinet (at) martin-expertise (dot) fr</p>
</body></html>"""

ACCUEIL_GAMMA = """<html><body><h1>Gamma Solutions</h1>
<p>Solutions logicielles - 85100 Les Sables-d'Olonne.</p></body></html>"""
CONTACT_GAMMA = """<html><body><p>Gamma Solutions - ecrivez a contact@gmail.com</p>
</body></html>"""

PAGES = {
    "https://dupont-avocats.fr": ACCUEIL_DUPONT,
    "https://dupont-avocats.fr/contact": CONTACT_DUPONT,
    "https://martin-expertise.fr": ACCUEIL_MARTIN,
    "https://martin-expertise.fr/contact": CONTACT_MARTIN,
    "https://gammasolutions.fr": ACCUEIL_GAMMA,
    "https://gammasolutions.fr/contact": CONTACT_GAMMA,
    # CABINET INVISIBLE CONSEIL n'a aucun site : rien ne repond pour lui.
}


OSM_ELEMENTS = [
    # notaire cartographie avec son adresse de contact : lead immediat
    {"type": "node", "id": 111, "tags": {
        "name": "Office notarial de Challans", "office": "notary",
        "email": "office@notaires-challans.fr", "addr:postcode": "85300",
        "addr:city": "Challans"}},
    # adresse nominative : ecartee
    {"type": "node", "id": 222, "tags": {
        "name": "Maitre Sicard", "office": "notary",
        "email": "fabienne.sicard@notaires.fr"}},
]


def _fausse_api(params):
    naf = params["activite_principale"]
    resultats = PAR_NAF.get(naf, [])
    if params.get("q") == "notaire":
        resultats = []          # aucun notaire dans le jeu de test SIRENE
    return {"total_results": len(resultats), "total_pages": 1, "results": resultats}


def _faux_overpass(requete):
    if '"office"="notary"' in requete:
        return {"elements": OSM_ELEMENTS}
    return {"elements": []}


@pytest.fixture
def environnement(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_client", lambda: FauxClient(
        pages=PAGES, api=_fausse_api, overpass=_faux_overpass))
    return {
        "base": str(tmp_path / "leads.db"),
        "opposition": str(tmp_path / "opposition.txt"),
        "export": tmp_path / "leads.csv",
    }


def _lancer(env, *args):
    return cli.main(["--base", env["base"], "--icp", str(CHEMIN_ICP),
                     "--opposition", env["opposition"], *args])


def _lire(chemin: Path) -> list[list[str]]:
    texte = chemin.read_text(encoding="utf-8-sig")
    lignes = list(csv.reader(texte.splitlines(), delimiter=";"))
    return [l[:18] for l in lignes if l]      # on ignore l'horodatage de collecte


def test_pipeline_complet_reproduit_le_fichier_de_reference(environnement):
    env = environnement

    assert _lancer(env, "collecte", "--segments", "avocats,experts-comptables,esn-it",
                   "--departements", "85", "--limite", "50") == 0
    assert _lancer(env, "enrichir", "--limite", "50", "--delai", "0", "--paralleles", "1") == 0
    assert _lancer(env, "exporter", "--out", str(env["export"]), "--score-min", "55") == 0

    assert _lire(env["export"]) == _lire(GOLDEN)


def test_structures_sans_site_et_leads_faibles_sont_ecartes(environnement):
    env = environnement
    _lancer(env, "collecte", "--segments", "avocats,experts-comptables,esn-it",
            "--departements", "85", "--limite", "50")
    _lancer(env, "enrichir", "--limite", "50", "--delai", "0", "--paralleles", "1")

    from leadgen.storage import Base

    base = Base(env["base"])
    assert base.stats()["entreprises"] == 4
    assert base.stats()["sites_trouves"] == 3        # CABINET INVISIBLE n'a pas de site

    emails = {l["email"] for l in base.leads()}
    assert "contact@gmail.com" in emails              # collecte mais non qualifie
    assert "jean.dupont@dupont-avocats.fr" not in emails
    assert "noreply@dupont-avocats.fr" not in emails
    assert "contact@agence-web.com" not in emails

    scores = {l["email"]: l["score"] for l in base.leads()}
    assert scores["contact@gmail.com"] < 55
    base.fermer()


def test_la_desinscription_sort_le_lead_des_exports(environnement):
    env = environnement
    _lancer(env, "collecte", "--segments", "avocats", "--departements", "85")
    _lancer(env, "enrichir", "--limite", "50", "--delai", "0", "--paralleles", "1")
    _lancer(env, "exporter", "--out", str(env["export"]), "--score-min", "55")
    avant = _lire(env["export"])

    assert _lancer(env, "desinscrire", "contact@dupont-avocats.fr") == 0
    _lancer(env, "exporter", "--out", str(env["export"]), "--score-min", "55",
            "--reexporter")
    apres = _lire(env["export"])

    assert any(l[0] == "contact@dupont-avocats.fr" for l in avant[1:])
    assert not any(l[0] == "contact@dupont-avocats.fr" for l in apres[1:])


def test_openstreetmap_donne_des_contacts_sans_crawl(environnement):
    env = environnement
    assert _lancer(env, "collecte", "--segments", "notaires",
                   "--sources", "osm", "--departements", "85") == 0

    from leadgen.storage import Base

    base = Base(env["base"])
    leads = {l["email"]: l for l in base.leads()}
    assert "office@notaires-challans.fr" in leads
    assert leads["office@notaires-challans.fr"]["source"] == "osm"
    assert "openstreetmap.org/node/111" in leads["office@notaires-challans.fr"]["source_url"]
    assert "fabienne.sicard@notaires.fr" not in leads      # nominative
    base.fermer()


def test_second_passage_ne_duplique_rien(environnement):
    env = environnement
    for _ in range(2):
        _lancer(env, "collecte", "--segments", "avocats", "--departements", "85")

    from leadgen.storage import Base

    base = Base(env["base"])
    assert base.stats()["entreprises"] == 2
    base.fermer()
