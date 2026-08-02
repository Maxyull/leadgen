from conftest import FauxClient, RobotsInterdit

from leadgen.enrich.emails import (
    CHEMINS_CONTACT,
    _dossier,
    collecter_emails,
    desobfusquer,
    extraire_emails,
    liens_utiles,
)

PAGE_CONTACT = """
<html><body>
  <h1>Nous contacter</h1>
  <a href="mailto:contact@dupont-avocats.fr">Ecrivez-nous</a>
  <p>Ou par courriel : secretariat (at) dupont-avocats (dot) fr</p>
  <p>Notre DPO : dpo@dupont-avocats.fr</p>
  <p>Ne pas repondre : noreply@dupont-avocats.fr</p>
  <p>Me Jean Dupont : jean.dupont@dupont-avocats.fr</p>
  <footer>Site realise par contact@agence-web.com</footer>
  <script>var mail = "tracking@analytics.io";</script>
</body></html>
"""


def test_desobfuscation():
    assert desobfusquer("contact (at) cabinet (dot) fr") == "contact@cabinet.fr"
    assert desobfusquer("contact [arobase] cabinet [point] fr") == "contact@cabinet.fr"
    assert desobfusquer("contact at cabinet.fr") == "contact@cabinet.fr"
    assert desobfusquer("deja@normal.fr") == "deja@normal.fr"


def test_extraction_toutes_adresses():
    trouves = extraire_emails(PAGE_CONTACT)
    assert "contact@dupont-avocats.fr" in trouves
    assert "secretariat@dupont-avocats.fr" in trouves
    assert "jean.dupont@dupont-avocats.fr" in trouves
    # le contenu des <script> est ignore
    assert "tracking@analytics.io" not in trouves


def test_collecte_filtre_et_priorise(robots, limiteur):
    client = FauxClient({"https://dupont-avocats.fr/contact": PAGE_CONTACT})
    resultats = collecter_emails(client, "https://dupont-avocats.fr", robots, limiteur)
    emails = [e for e, _ in resultats]

    assert emails[0] == "contact@dupont-avocats.fr"      # generique en tete
    assert "secretariat@dupont-avocats.fr" in emails
    assert "dpo@dupont-avocats.fr" in emails
    assert "noreply@dupont-avocats.fr" not in emails      # technique
    assert "jean.dupont@dupont-avocats.fr" not in emails  # nominative
    assert "contact@agence-web.com" not in emails         # prestataire, autre domaine
    assert all(url.endswith("/contact") for _, url in resultats)


def test_collecte_autorise_les_nominatives_sur_demande(robots, limiteur):
    client = FauxClient({"https://dupont-avocats.fr/contact": PAGE_CONTACT})
    emails = [e for e, _ in collecter_emails(
        client, "https://dupont-avocats.fr", robots, limiteur, autoriser_nominatif=True)]
    assert "jean.dupont@dupont-avocats.fr" in emails
    assert emails.index("contact@dupont-avocats.fr") < emails.index("jean.dupont@dupont-avocats.fr")


def test_collecte_respecte_robots(limiteur):
    client = FauxClient({"https://dupont-avocats.fr/contact": PAGE_CONTACT})
    recolte = collecter_emails(
        client, "https://dupont-avocats.fr", RobotsInterdit("/contact"), limiteur)
    assert recolte.emails == []
    assert not any(a.endswith("/contact") for a in client.appels)


def test_collecte_borne_le_nombre_de_pages(robots, limiteur):
    client = FauxClient({})
    collecter_emails(client, "https://vide.fr", robots, limiteur, max_pages=5)
    assert len(client.appels) <= len(CHEMINS_CONTACT)


def test_liens_utiles_repere_les_pages_de_coordonnees():
    html = """<html><body>
      <a href="/nous-joindre">Nous joindre</a>
      <a href="/coordonnees.html">Où nous trouver</a>
      <a href="/blog/article-42">Actualités</a>
      <a href="https://www.linkedin.com/in/x">LinkedIn</a>
      <a href="mailto:x@y.fr">mail</a>
      <a href="#haut">haut de page</a>
      <a href="/fr/mentions-legales#bas">Mentions légales</a>
    </body></html>"""
    liens = liens_utiles(html, "https://cabinet.fr/")
    assert liens == [
        "https://cabinet.fr/nous-joindre",
        "https://cabinet.fr/coordonnees.html",
        "https://cabinet.fr/fr/mentions-legales",
    ]


def test_dossier_dune_url():
    assert _dossier("https://x.fr") == "https://x.fr/"
    assert _dossier("https://x.fr/") == "https://x.fr/"
    assert _dossier("https://x.fr/fr/accueil.html") == "https://x.fr/fr/"
    assert _dossier("https://x.fr/fr/") == "https://x.fr/fr/"


def test_liens_utiles_reste_sur_le_domaine():
    html = '<a href="https://autre-cabinet.fr/contact">contact</a>'
    assert liens_utiles(html, "https://cabinet.fr/") == []


def test_suit_le_vrai_lien_de_contact_du_site(robots, limiteur):
    """Le site n'utilise aucun chemin standard : seul son menu le dit."""
    accueil = '<html><body><a href="/nous-joindre">Nous joindre</a></body></html>'
    joindre = '<html><body><a href="mailto:etude@notaire-x.fr">nous</a></body></html>'
    client = FauxClient({"https://notaire-x.fr": accueil,
                         "https://notaire-x.fr/nous-joindre": joindre})
    recolte = collecter_emails(client, "https://notaire-x.fr", robots, limiteur)
    assert [e for e, _ in recolte.emails] == ["etude@notaire-x.fr"]
    assert client.appels[1] == "https://notaire-x.fr/nous-joindre"


def test_arret_des_qu_une_boite_generique_est_trouvee(robots, limiteur):
    """On ne frappe pas 10 URL quand contact@ est deja sur la page d'accueil."""
    accueil = '<html><body><a href="mailto:contact@cabinet.fr">nous</a></body></html>'
    client = FauxClient({"https://cabinet.fr": accueil,
                         "https://cabinet.fr/contact": accueil})
    recolte = collecter_emails(client, "https://cabinet.fr", robots, limiteur)
    assert [e for e, _ in recolte.emails] == ["contact@cabinet.fr"]
    assert len(client.appels) == 1


def test_pas_d_arret_sur_une_adresse_exterieure(robots, limiteur):
    """contact@agence-web.com ne doit pas faire croire qu'on a trouve."""
    accueil = '<html><body><a href="mailto:contact@agence-web.com">agence</a></body></html>'
    contact = '<html><body><a href="mailto:cabinet@cabinet.fr">nous</a></body></html>'
    client = FauxClient({"https://cabinet.fr": accueil,
                         "https://cabinet.fr/contact": contact})
    recolte = collecter_emails(client, "https://cabinet.fr", robots, limiteur)
    assert [e for e, _ in recolte.emails] == ["cabinet@cabinet.fr"]
    assert len(client.appels) == 2


def test_repli_sur_une_messagerie_connue(robots, limiteur):
    """Beaucoup de petites structures n'ont qu'une boite gmail ou de branche."""
    page = ('<a href="mailto:contact@gmail.com">nous ecrire</a>'
            '<a href="mailto:etude.martin@notaires.fr">etude</a>')
    client = FauxClient({"https://petit-cabinet.fr/contact": page})
    recolte = collecter_emails(client, "https://petit-cabinet.fr", robots, limiteur)
    assert [e for e, _ in recolte.emails] == ["contact@gmail.com",
                                              "etude.martin@notaires.fr"]


def test_adresse_technique_d_hebergeur_refusee(robots, limiteur):
    """Vu en production : contact@...hostingersite.com sur le site d'un cabinet."""
    page = '<a href="mailto:contact@midnightblue-narwhal-974025.hostingersite.com">x</a>'
    client = FauxClient({"https://cabinet-x.fr/contact": page})
    recolte = collecter_emails(client, "https://cabinet-x.fr", robots, limiteur)
    assert recolte.emails == []
