from leadgen.geo import DEPARTEMENTS, REGIONS, resoudre_departements, zones_osm


def test_liste_des_departements():
    assert len(DEPARTEMENTS) == 101
    for code in ("01", "2A", "2B", "85", "95", "971", "976"):
        assert code in DEPARTEMENTS
    assert "20" not in DEPARTEMENTS          # la Corse, c'est 2A/2B
    assert len(DEPARTEMENTS) == len(set(DEPARTEMENTS))


def test_mot_cle_national():
    assert resoudre_departements(["tous"]) == DEPARTEMENTS
    assert resoudre_departements(["france"]) == DEPARTEMENTS
    assert resoudre_departements(["85", "44"]) == ["85", "44"]
    assert resoudre_departements([]) == []


def test_maille_osm_locale():
    zones, niveau = zones_osm(["85", "44"])
    assert (zones, niveau) == (["85", "44"], "departement")


def test_maille_osm_nationale():
    zones, niveau = zones_osm(DEPARTEMENTS)
    assert niveau == "region"
    assert len(zones) == len(REGIONS) == 18
