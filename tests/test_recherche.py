from conftest import FauxClient, FausseReponse

from leadgen.enrich.recherche import (
    candidats,
    candidats_brave,
    candidats_devines,
    candidats_google,
)
from leadgen.models import Entreprise

CABINET = Entreprise(siren="1", nom="CABINET DUPONT AVOCATS", naf="69.10Z",
                     segment="avocats", ville="LA ROCHE-SUR-YON")


class ClientBrave:
    def __init__(self, resultats, status=200):
        self.resultats = resultats
        self.status = status
        self.derniere_requete = None
        self.entetes = None

    def get(self, url, params=None, headers=None, **kwargs):
        self.derniere_requete = (params or {}).get("q")
        self.entetes = headers or {}
        return FausseReponse(url, status=self.status,
                             donnees={"web": {"results": self.resultats}})


def test_devine_sans_reseau():
    urls = candidats_devines(CABINET)
    assert "https://dupont-avocats.fr" in urls


def test_brave_sans_cle_ne_fait_rien(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    client = FauxClient()
    assert candidats_brave(client, CABINET) == []
    assert client.appels == []


def test_brave_retient_les_sites_officiels(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "cle-test")
    client = ClientBrave([
        {"url": "https://www.linkedin.com/company/dupont"},
        {"url": "https://www.pagesjaunes.fr/pros/dupont"},
        {"url": "https://dupont-avocats.fr/equipe"},
        {"url": "https://dupont-avocats.fr/contact"},
        {"url": "https://avocats-dupont.com/"},
    ])
    urls = candidats_brave(client, CABINET)

    assert urls == ["https://dupont-avocats.fr", "https://avocats-dupont.com"]
    assert "CABINET DUPONT AVOCATS" in client.derniere_requete
    assert "LA ROCHE-SUR-YON" in client.derniere_requete
    assert client.entetes["X-Subscription-Token"] == "cle-test"


def test_brave_en_panne_ne_bloque_pas(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "cle-test")
    assert candidats_brave(ClientBrave([], status=500), CABINET) == []


def test_le_fournisseur_brave_ne_renvoie_que_le_moteur(monkeypatch):
    """La devinette n'est pas melangee : l'appelant enchaine gratuit puis payant."""
    monkeypatch.setenv("BRAVE_API_KEY", "cle-test")
    client = ClientBrave([{"url": "https://dupont-avocats.fr/"}])
    assert candidats(client, CABINET, "brave") == ["https://dupont-avocats.fr"]


def test_moteur_aucun():
    assert candidats(FauxClient(), CABINET, "aucun") == []


class ClientGoogle:
    def __init__(self, items, status=200):
        self.items = items
        self.status = status
        self.params = None

    def get(self, url, params=None, **kwargs):
        self.params = params or {}
        return FausseReponse(url, status=self.status, donnees={"items": self.items})


def test_google_sans_identifiants(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)
    client = FauxClient()
    assert candidats_google(client, CABINET) == []
    assert client.appels == []


def test_google_exige_les_deux_identifiants(monkeypatch):
    """Une cle sans moteur de recherche personnalise ne sert a rien."""
    monkeypatch.setenv("GOOGLE_API_KEY", "cle")
    monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)
    assert candidats_google(FauxClient(), CABINET) == []


def test_google_retient_les_sites_officiels(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "cle")
    monkeypatch.setenv("GOOGLE_CSE_ID", "cx-test")
    client = ClientGoogle([
        {"link": "https://www.pagesjaunes.fr/pros/dupont"},
        {"link": "https://dupont-avocats.fr/equipe"},
        {"link": "https://dupont-avocats.fr/contact"},
    ])
    assert candidats_google(client, CABINET) == ["https://dupont-avocats.fr"]
    assert client.params["cx"] == "cx-test"
    assert client.params["gl"] == "fr"


def test_google_quota_epuise(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "cle")
    monkeypatch.setenv("GOOGLE_CSE_ID", "cx")
    assert candidats_google(ClientGoogle([], status=429), CABINET) == []


def test_selection_du_moteur(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "cle")
    monkeypatch.setenv("GOOGLE_CSE_ID", "cx")
    client = ClientGoogle([{"link": "https://dupont-avocats.fr/"}])
    assert candidats(client, CABINET, "google") == ["https://dupont-avocats.fr"]
