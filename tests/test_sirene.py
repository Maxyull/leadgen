from conftest import FauxClient

from leadgen.sources.sirene import construire_params, parser_resultat, rechercher

BRUT = {
    "siren": "111111111",
    "nom_complet": "CABINET DUPONT AVOCATS",
    "nom_raison_sociale": "CABINET DUPONT AVOCATS",
    "activite_principale": "69.10Z",
    "categorie_entreprise": "PME",
    "date_creation": "2015-03-01",
    "date_fermeture": None,
    "dirigeants": [{"nom": "DUPONT", "prenoms": "JEAN", "annee_de_naissance": "1970"}],
    "siege": {
        "code_postal": "85000",
        "libelle_commune": "LA ROCHE-SUR-YON",
        "departement": "85",
        "tranche_effectif_salarie": "12",
        "adresse": "12 RUE DES HALLES 85000 LA ROCHE-SUR-YON",
        "etat_administratif": "A",
        "activite_principale": "69.10Z",
    },
}


def test_parsing_ne_conserve_aucune_donnee_de_dirigeant():
    e = parser_resultat(BRUT, "avocats")
    assert e.siren == "111111111"
    assert e.ville == "LA ROCHE-SUR-YON"
    assert e.tranche_effectif == "12"
    assert "DUPONT" not in str(e.to_dict().values()).replace("CABINET DUPONT AVOCATS", "")
    assert "dirigeants" not in e.to_dict()


def test_parsing_ignore_les_structures_fermees():
    ferme = {**BRUT, "siege": {**BRUT["siege"], "etat_administratif": "F"}}
    assert parser_resultat(ferme, "avocats") is None
    cessee = {**BRUT, "date_fermeture": "2024-01-01"}
    assert parser_resultat(cessee, "avocats") is None
    assert parser_resultat({"nom_complet": "SANS SIREN"}, "avocats") is None


def test_params_de_recherche():
    p = construire_params("69.10Z", 2, departement="85", effectifs=["11", "12"])
    assert p["activite_principale"] == "69.10Z"
    assert p["page"] == 2
    assert p["departement"] == "85"
    assert p["tranche_effectif_salarie"] == "11,12"
    assert p["etat_administratif"] == "A"


def _api_deux_pages(params):
    page = params["page"]
    if page == 1:
        return {"total_results": 2, "total_pages": 2, "results": [BRUT]}
    autre = {**BRUT, "siren": "222222222", "nom_complet": "SCP MARTIN"}
    return {"total_results": 2, "total_pages": 2, "results": [autre]}


def test_pagination():
    client = FauxClient(api=_api_deux_pages)
    resultats = list(rechercher(client, "69.10Z", "avocats", limite=10, delai=0))
    assert [e.siren for e in resultats] == ["111111111", "222222222"]


def test_limite_respectee():
    client = FauxClient(api=_api_deux_pages)
    resultats = list(rechercher(client, "69.10Z", "avocats", limite=1, delai=0))
    assert len(resultats) == 1


def test_siege_strict_ecarte_les_reseaux_nationaux():
    national = {**BRUT, "siren": "999999999", "nom_complet": "FIDAL",
                "siege": {**BRUT["siege"], "departement": "92", "code_postal": "92400"}}

    def api(params):
        return {"total_results": 2, "total_pages": 1, "results": [BRUT, national]}

    client = FauxClient(api=api)
    strict = list(rechercher(client, "69.10Z", "avocats", departement="85",
                             limite=10, delai=0))
    assert [e.siren for e in strict] == ["111111111"]

    client = FauxClient(api=api)
    large = list(rechercher(client, "69.10Z", "avocats", departement="85",
                            limite=10, siege_strict=False, delai=0))
    assert len(large) == 2


def test_erreur_api_remontee():
    client = FauxClient(api=lambda p: {"erreur": "activite_principale invalide"})
    try:
        list(rechercher(client, "6910Z", "avocats", delai=0))
    except ValueError as exc:
        assert "activite_principale" in str(exc)
    else:
        raise AssertionError("une erreur API doit lever ValueError")
