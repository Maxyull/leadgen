import pytest

from leadgen.config import CHEMIN_ICP, charger_icp


@pytest.fixture(scope="module")
def icp():
    return charger_icp(CHEMIN_ICP)


def test_icp_livre_est_valide(icp):
    assert icp.segments
    for cle, segment in icp.segments.items():
        assert segment["naf"], f"{cle} sans code NAF"
        assert 1 <= segment["priorite"] <= 5
        assert segment["argument"]
        for naf in segment["naf"]:
            # format attendu par l'API : 69.10Z
            assert len(naf) == 6 and naf[2] == "." and naf[-1].isalpha(), naf


def test_effectifs_cibles_connus(icp):
    for code in icp.effectifs:
        assert code in icp.effectifs_libelles


def test_resolution_des_segments(icp):
    tous = icp.resoudre([])
    assert len(tous) == len(icp.segments)
    assert tous[0]["priorite"] >= tous[-1]["priorite"]

    choisis = icp.resoudre(["avocats", "esn-it"])
    assert [s["cle"] for s in choisis] == ["avocats", "esn-it"]


def test_segment_inconnu(icp):
    with pytest.raises(KeyError):
        icp.resoudre(["boulangeries"])
