import pytest

from leadgen.compliance import (
    CacheRobots,
    LimiteurDebit,
    ListeOpposition,
    classer_email,
    email_exploitable,
    est_boite_connue,
    normaliser_email,
)


@pytest.mark.parametrize("email,attendu", [
    ("contact@cabinet-dupont.fr", "generique"),
    ("CONTACT@Cabinet-Dupont.FR", "generique"),
    ("info@x.fr", "generique"),
    ("secretariat@x.fr", "generique"),
    ("contact.paris@x.fr", "generique"),
    ("rh@x.fr", "fonction"),
    ("dpo@x.fr", "fonction"),
    ("recrutement-lyon@x.fr", "fonction"),
    ("noreply@x.fr", "technique"),
    ("no-reply@x.fr", "technique"),
    ("abuse@x.fr", "technique"),
    ("jean.dupont@x.fr", "nominatif"),
    ("m.martin@x.fr", "nominatif"),
])
def test_classement_des_adresses(email, attendu):
    assert classer_email(email) == attendu


def test_les_nominatives_sont_ecartees_par_defaut():
    assert email_exploitable("contact@x.fr") is True
    assert email_exploitable("jean.dupont@x.fr") is False
    assert email_exploitable("jean.dupont@x.fr", autoriser_nominatif=True) is True


def test_les_adresses_techniques_sont_toujours_refusees():
    assert email_exploitable("noreply@x.fr", autoriser_nominatif=True) is False
    assert email_exploitable("postmaster@x.fr") is False


def test_refus_des_faux_positifs():
    assert email_exploitable("logo@2x.png") is False
    assert email_exploitable("contact@example.com") is False
    assert email_exploitable("pas-une-adresse") is False


def test_refus_des_hebergeurs_et_plateformes():
    """Vu en production : l'adresse de l'hebergeur trainait sur le site."""
    assert email_exploitable("support@ovh.com") is False
    assert email_exploitable("contact@narwhal-974025.hostingersite.com") is False


def test_boites_connues():
    assert est_boite_connue("gmail.com") is True
    assert est_boite_connue("orange.fr") is True
    assert est_boite_connue("notaires.fr") is True
    assert est_boite_connue("44043.notaires.fr") is True      # sous-domaine d'office
    assert est_boite_connue("narwhal-974025.hostingersite.com") is False
    assert est_boite_connue("") is False


def test_normalisation():
    assert normaliser_email("  Contact@X.FR,  ") == "contact@x.fr"


def test_liste_opposition(tmp_path):
    fichier = tmp_path / "opposition.txt"
    fichier.write_text(
        "# commentaire\ncontact@refus.fr\n@domaine-banni.fr\n", encoding="utf-8"
    )
    liste = ListeOpposition(fichier)
    assert liste.contient("CONTACT@refus.fr")
    assert liste.contient("nimporte@domaine-banni.fr")
    assert not liste.contient("contact@ok.fr")

    liste.ajouter("nouveau@refus.fr", motif="plainte")
    assert liste.contient("nouveau@refus.fr")
    assert "plainte" in fichier.read_text(encoding="utf-8")

    relue = ListeOpposition(fichier)
    assert relue.contient("nouveau@refus.fr")


def test_liste_opposition_filtre():
    class Vide(ListeOpposition):
        def __init__(self):
            self.emails = {"a@x.fr"}
            self.domaines = set()

    assert Vide().filtrer(["a@x.fr", "b@x.fr"]) == ["b@x.fr"]


def test_robots_respecte_les_interdictions():
    robots_txt = "User-agent: *\nDisallow: /prive\n"
    cache = CacheRobots(fetch=lambda url: robots_txt)
    assert cache.autorise("https://x.fr/contact") is True
    assert cache.autorise("https://x.fr/prive/liste") is False


def test_robots_absent_autorise():
    cache = CacheRobots(fetch=lambda url: (_ for _ in ()).throw(ConnectionError()))
    assert cache.autorise("https://x.fr/contact") is True


def test_robots_desactive():
    cache = CacheRobots(fetch=lambda url: "User-agent: *\nDisallow: /", actif=False)
    assert cache.autorise("https://x.fr/quoi-que-ce-soit") is True


def test_limiteur_espace_les_requetes():
    import time

    limiteur = LimiteurDebit(delai=0.05)
    limiteur.attendre("https://x.fr/a")
    debut = time.monotonic()
    limiteur.attendre("https://x.fr/b")
    assert time.monotonic() - debut >= 0.04
    # domaine different : pas d'attente
    debut = time.monotonic()
    limiteur.attendre("https://autre.fr/a")
    assert time.monotonic() - debut < 0.04
