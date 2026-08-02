from conftest import FauxClient, RobotsInterdit

from leadgen.enrich.website import (
    domaines_candidats,
    jetons,
    jetons_forts,
    page_correspond,
    slugs_candidats,
    trouver_site,
)

PAGE_CABINET = """
<html><head><title>Cabinet Dupont Avocats</title></head><body>
  <p>Le cabinet Dupont vous accueille a La Roche-sur-Yon (85000).</p>
</body></html>
"""
PAGE_HOMONYME = """
<html><body><h1>Dupont Traiteur, Lille</h1><p>Reception et buffets.</p></body></html>
"""


def test_jetons_retirent_la_forme_juridique():
    assert jetons("SELARL CABINET DUPONT AVOCATS") == ["cabinet", "dupont", "avocats"]
    assert jetons_forts("SELARL CABINET DUPONT AVOCATS") == ["dupont"]


def test_slugs_proposent_la_forme_metier():
    slugs = slugs_candidats("CABINET DUPONT AVOCATS")
    assert "dupont" in slugs
    assert "dupont-avocats" in slugs


def test_domaines_candidats_privilegient_le_fr():
    urls = domaines_candidats("CABINET DUPONT AVOCATS")
    assert urls[0].endswith(".fr")
    assert all(u.startswith("https://") for u in urls)
    assert len(urls) == len(set(urls))
    assert len(urls) <= 12


def test_page_correspond_accepte_la_bonne_structure():
    assert page_correspond(PAGE_CABINET, "CABINET DUPONT AVOCATS", "85000",
                           "LA ROCHE-SUR-YON") is True


def test_page_correspond_rejette_un_homonyme():
    assert page_correspond(PAGE_HOMONYME, "CABINET MARTIN AVOCATS", "85000",
                           "LA ROCHE-SUR-YON") is False


def test_page_correspond_accepte_le_siren():
    html = "<p>Mentions legales - SIREN 111 111 111</p>"
    assert page_correspond(html, "STRUCTURE SANS NOM PARLANT", siren="111111111") is True


def test_trouver_site_ignore_les_domaines_morts(entreprise_avocats, robots, limiteur):
    client = FauxClient(
        pages={"https://dupont-avocats.fr": PAGE_CABINET},
        injoignables={"https://dupont.fr"},
    )
    site = trouver_site(client, entreprise_avocats, robots, limiteur)
    assert site == "https://dupont-avocats.fr"
    assert "https://dupont.fr" in client.appels  # il a bien ete tente


def test_trouver_site_refuse_un_homonyme(entreprise_avocats, robots, limiteur):
    """Meme patronyme, autre metier, autre ville : ce n'est pas notre cible."""
    client = FauxClient(pages={"https://dupont.fr": PAGE_HOMONYME})
    assert trouver_site(client, entreprise_avocats, robots, limiteur) is None


def test_trouver_site_respecte_robots(entreprise_avocats, limiteur):
    client = FauxClient(pages={"https://dupont.fr": PAGE_CABINET})
    site = trouver_site(client, entreprise_avocats, RobotsInterdit("dupont"), limiteur)
    assert site is None
    assert client.appels == []


def test_nom_vide_ne_plante_pas():
    assert slugs_candidats("SARL") == []
    assert domaines_candidats("SARL") == []
