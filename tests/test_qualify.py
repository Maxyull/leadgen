from leadgen.models import Entreprise
from leadgen.qualify import SEUIL_QUALIFIE, est_qualifie, noter


def _entreprise(**kw):
    base = dict(siren="1", nom="X", naf="69.10Z", segment="avocats",
                tranche_effectif="12", date_creation="2015-01-01")
    base.update(kw)
    return Entreprise(**base)


def test_score_maximal_pour_le_coeur_de_cible():
    score, raisons = noter(_entreprise(), "contact@cabinet.fr", priorite_segment=5)
    assert score == 100
    assert any("generique" in r for r in raisons)


def test_boite_grand_public_penalisee():
    haut, _ = noter(_entreprise(), "contact@cabinet.fr", 5)
    bas, raisons = noter(_entreprise(), "contact@gmail.com", 5)
    assert bas == haut - 12
    assert any("grand public" in r for r in raisons)


def test_adresse_nominative_moins_bien_notee():
    generique, _ = noter(_entreprise(), "contact@cabinet.fr", 5)
    nominative, _ = noter(_entreprise(), "jean.dupont@cabinet.fr", 5)
    assert nominative < generique


def test_segment_secondaire_moins_bien_note():
    fort, _ = noter(_entreprise(segment="avocats"), "contact@x.fr", 5)
    faible, _ = noter(_entreprise(segment="immobilier-gestion"), "contact@x.fr", 2)
    assert fort - faible == 18


def test_effectif_extreme_penalise():
    milieu, _ = noter(_entreprise(tranche_effectif="12"), "contact@x.fr", 5)
    micro, _ = noter(_entreprise(tranche_effectif="00"), "contact@x.fr", 5)
    geant, _ = noter(_entreprise(tranche_effectif="53"), "contact@x.fr", 5)
    assert milieu > micro
    assert milieu > geant


def test_sans_site_le_score_baisse():
    avec, _ = noter(_entreprise(), "contact@x.fr", 5, site_trouve=True)
    sans, _ = noter(_entreprise(), "contact@x.fr", 5, site_trouve=False)
    assert avec - sans == 10


def test_score_borne():
    score, _ = noter(_entreprise(tranche_effectif="NN", date_creation=""),
                     "contact@gmail.com", 1, site_trouve=False)
    assert 0 <= score <= 100


def test_seuil():
    assert est_qualifie(SEUIL_QUALIFIE) is True
    assert est_qualifie(SEUIL_QUALIFIE - 1) is False
