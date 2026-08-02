import pytest
from conftest import FauxClient

from leadgen.sources.osm import construire_requete, parser_element, rechercher

NOEUD_COMPLET = {
    "type": "node", "id": 4413316989,
    "tags": {
        "name": "Cabinet Jegou", "office": "accountant",
        "email": "contact@cabinetjegou.fr", "website": "cabinetjegou.fr",
        "addr:postcode": "85170", "addr:city": "Le Poire-sur-Vie",
        "addr:housenumber": "12", "addr:street": "Rue des Lilas",
        "phone": "+33 6 82 22 94 07",
    },
}
NOEUD_NOMINATIF = {
    "type": "node", "id": 5549693093,
    "tags": {"name": "Maitre Fabienne Sicard", "office": "notary",
             "email": "fabienne.sicard@notaires.fr"},
}
NOEUD_SANS_NOM = {"type": "way", "id": 1, "tags": {"office": "lawyer"}}


def test_requete_overpass():
    requete = construire_requete(["office=lawyer", "office=notary"], "85")
    assert 'area["ref:INSEE"="85"]["admin_level"="6"]->.zone;' in requete
    assert 'nwr["office"="lawyer"](area.zone);' in requete
    assert 'nwr["office"="notary"](area.zone);' in requete
    assert requete.strip().endswith("out center tags;")


def test_requete_par_region():
    requete = construire_requete(["office=notary"], "52", niveau="region")
    assert 'area["ref:INSEE"="52"]["admin_level"="4"]->.zone;' in requete


def test_requete_exige_une_zone_valide():
    with pytest.raises(ValueError):
        construire_requete(["office=lawyer"], "")
    with pytest.raises(ValueError):
        construire_requete([], "85")
    with pytest.raises(ValueError):
        construire_requete(["office=lawyer"], "85", niveau="commune")


def test_parsing_complet():
    e = parser_element(NOEUD_COMPLET, "experts-comptables", "85")
    assert e.siren == "osm:node/4413316989"
    assert e.source == "osm"
    assert e.site == "https://cabinetjegou.fr"       # protocole ajoute
    assert e.site_statut == "trouve"
    assert e.email_public == "contact@cabinetjegou.fr"
    assert e.code_postal == "85170"
    assert "Rue des Lilas" in e.adresse


def test_parsing_sans_site():
    e = parser_element(NOEUD_NOMINATIF, "notaires", "85")
    assert e.site is None
    assert e.site_statut == "inconnu"
    assert e.email_public == "fabienne.sicard@notaires.fr"


def test_element_sans_nom_ignore():
    assert parser_element(NOEUD_SANS_NOM, "avocats", "85") is None


def test_recherche_complete():
    client = FauxClient(overpass=lambda requete: {
        "elements": [NOEUD_COMPLET, NOEUD_NOMINATIF, NOEUD_SANS_NOM]
    })
    resultats = list(rechercher(client, ["office=accountant"], "experts-comptables",
                                "85", delai=0))
    assert [e.nom for e in resultats] == ["Cabinet Jegou", "Maitre Fabienne Sicard"]


def test_retente_apres_un_429(monkeypatch):
    monkeypatch.setattr("leadgen.sources.osm.ATTENTE_RETRY", 0.0)
    etat = {"appels": 0}

    def overpass(requete):
        etat["appels"] += 1
        if etat["appels"] == 1:
            return 429
        return {"elements": [NOEUD_COMPLET]}

    client = FauxClient(overpass=overpass)
    resultats = list(rechercher(client, ["office=accountant"], "experts-comptables",
                                "85", delai=0))
    assert [e.nom for e in resultats] == ["Cabinet Jegou"]
    assert etat["appels"] == 2


def test_abandon_apres_trois_echecs(monkeypatch):
    monkeypatch.setattr("leadgen.sources.osm.ATTENTE_RETRY", 0.0)
    etat = {"appels": 0}

    def overpass(requete):
        etat["appels"] += 1
        return 504

    client = FauxClient(overpass=overpass)
    assert list(rechercher(client, ["office=notary"], "notaires", "85", delai=0)) == []
    assert etat["appels"] == 3


def test_limite():
    client = FauxClient(overpass=lambda r: {"elements": [NOEUD_COMPLET, NOEUD_NOMINATIF]})
    assert len(list(rechercher(client, ["office=notary"], "notaires", "85",
                               limite=1, delai=0))) == 1
