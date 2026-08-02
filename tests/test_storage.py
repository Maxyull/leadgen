import pytest

from leadgen.models import Entreprise, Lead
from leadgen.storage import Base


@pytest.fixture
def base(tmp_path):
    b = Base(tmp_path / "test.db")
    yield b
    b.fermer()


def _entreprise(siren="111111111", **kw):
    base = dict(siren=siren, nom="CABINET DUPONT", naf="69.10Z", segment="avocats",
                code_postal="85000", ville="LA ROCHE-SUR-YON", departement="85",
                tranche_effectif="12", date_creation="2015-01-01")
    base.update(kw)
    return Entreprise(**base)


def _lead(email="contact@dupont.fr", **kw):
    base = dict(siren="111111111", nom="CABINET DUPONT", segment="avocats",
                email=email, type_email="generique", score=90)
    base.update(kw)
    return Lead(**base)


def test_entreprise_inseree_une_seule_fois(base):
    assert base.enregistrer_entreprise(_entreprise()) is True
    assert base.enregistrer_entreprise(_entreprise(nom="CABINET DUPONT ET FILS")) is False
    assert base.stats()["entreprises"] == 1
    assert base.entreprises_a_enrichir()[0].nom == "CABINET DUPONT ET FILS"


def test_email_dedoublonne_entre_structures(base):
    base.enregistrer_entreprise(_entreprise())
    base.enregistrer_entreprise(_entreprise(siren="222222222", nom="AUTRE"))
    assert base.enregistrer_lead(_lead()) is True
    assert base.enregistrer_lead(_lead(siren="222222222", nom="AUTRE")) is False
    assert base.stats()["leads"] == 1


def test_file_d_enrichissement(base):
    base.enregistrer_entreprise(_entreprise())
    base.enregistrer_entreprise(_entreprise(siren="222222222", segment="sante"))
    assert len(base.entreprises_a_enrichir()) == 2
    assert len(base.entreprises_a_enrichir(segments=["sante"])) == 1

    # 'trouve' = site connu mais emails pas encore extraits : reste dans la file
    base.maj_site("111111111", "https://dupont.fr", "trouve")
    assert len(base.entreprises_a_enrichir()) == 2

    base.maj_site("111111111", "https://dupont.fr", "traite")
    restants = base.entreprises_a_enrichir()
    assert [e.siren for e in restants] == ["222222222"]
    assert base.stats()["sites_trouves"] == 1


def test_selection_par_score_et_statut(base):
    base.enregistrer_entreprise(_entreprise())
    base.enregistrer_lead(_lead("a@x.fr", score=90))
    base.enregistrer_lead(_lead("b@x.fr", score=40))
    assert [l["email"] for l in base.leads(score_min=55)] == ["a@x.fr"]

    base.marquer_statut(["a@x.fr"], "exporte")
    assert base.leads(score_min=55, statut="nouveau") == []
    assert len(base.leads(score_min=55, statut="exporte")) == 1
    assert base.stats()["leads_exportes"] == 1


def test_renotation(base):
    base.enregistrer_entreprise(_entreprise())
    base.enregistrer_lead(_lead("a@x.fr", score=40))
    base.enregistrer_lead(_lead("b@x.fr", score=90))

    # le nouveau bareme double le score de a@ et laisse b@ tel quel
    def calcul(ligne):
        if ligne["email"] == "a@x.fr":
            return 80, ["nouveau bareme"]
        return 90, ["inchange"]

    assert base.renoter(calcul) == 1        # seul a@ a change
    scores = {l["email"]: l["score"] for l in base.leads()}
    assert scores == {"a@x.fr": 80, "b@x.fr": 90}
    ligne = base.conn.execute(
        "SELECT raisons FROM leads WHERE email = 'a@x.fr'").fetchone()
    assert ligne["raisons"] == "nouveau bareme"


def test_renotation_voit_les_donnees_de_l_entreprise(base):
    base.enregistrer_entreprise(_entreprise(tranche_effectif="22",
                                            date_creation="2001-01-01"))
    base.enregistrer_lead(_lead("a@x.fr", score=0))
    vues = []
    base.renoter(lambda l: (vues.append(dict(l)) or 50, []))
    assert vues[0]["tranche_effectif"] == "22"
    assert vues[0]["date_creation"] == "2001-01-01"


def test_renotation_sans_entreprise_liee(base):
    """Un lead orphelin ne doit pas faire planter la renotation."""
    base.enregistrer_lead(_lead("orphelin@x.fr", siren="inconnu", score=10))
    assert base.renoter(lambda l: (33, ["recalcule"])) == 1


def test_reprise_des_sites_introuvables(base):
    base.enregistrer_entreprise(_entreprise("111111111"))
    base.enregistrer_entreprise(_entreprise("222222222"))
    base.maj_site("111111111", None, "introuvable", moteur="devine")
    base.maj_site("222222222", None, "introuvable", moteur="brave")
    assert base.entreprises_a_enrichir() == []

    # brave reprend ce que la devinette a rate, mais pas ses propres echecs
    assert base.remettre_en_file("sites-introuvables", moteur="brave") == 1
    assert [e.siren for e in base.entreprises_a_enrichir()] == ["111111111"]

    # la devinette ne reprend pas les echecs de brave
    assert base.remettre_en_file("sites-introuvables", moteur="devine") == 0


def test_reprise_sans_filtre_de_moteur(base):
    base.enregistrer_entreprise(_entreprise())
    base.maj_site("111111111", None, "introuvable", moteur="brave")
    assert base.remettre_en_file("sites-introuvables") == 1
    assert len(base.entreprises_a_enrichir()) == 1


def test_reprise_des_sites_sans_contact(base):
    base.enregistrer_entreprise(_entreprise("111111111"))
    base.enregistrer_entreprise(_entreprise("222222222"))
    base.maj_site("111111111", "https://a.fr", "traite")
    base.maj_site("222222222", "https://b.fr", "traite")
    base.enregistrer_lead(_lead("contact@a.fr", siren="111111111"))
    assert base.entreprises_a_enrichir() == []

    # seule la structure qui n'a donne aucune adresse revient
    assert base.remettre_en_file("sites-sans-contact") == 1
    assert [e.siren for e in base.entreprises_a_enrichir()] == ["222222222"]


def test_reprise_inconnue(base):
    with pytest.raises(ValueError):
        base.remettre_en_file("nimporte-quoi")


def test_deux_connexions_simultanees(tmp_path):
    """Collecter et enrichir en meme temps ne doit pas verrouiller la base."""
    chemin = tmp_path / "concurrent.db"
    a, b = Base(chemin), Base(chemin)
    a.enregistrer_entreprise(_entreprise())
    b.enregistrer_entreprise(_entreprise(siren="222222222"))
    assert a.stats()["entreprises"] == 2
    assert b.stats()["entreprises"] == 2
    a.fermer()
    b.fermer()


def test_journal(base):
    base.journaliser("collecte", "avocats", {"nouvelles": 3})
    ligne = base.conn.execute("SELECT * FROM journal").fetchone()
    assert ligne["action"] == "collecte"
    assert "3" in ligne["detail"]
    assert ligne["horodat"]


def test_reouverture_conserve_les_donnees(tmp_path):
    chemin = tmp_path / "persist.db"
    b1 = Base(chemin)
    b1.enregistrer_entreprise(_entreprise())
    b1.fermer()
    b2 = Base(chemin)
    assert b2.stats()["entreprises"] == 1
    b2.fermer()
