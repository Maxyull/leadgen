import os

from leadgen.config import charger_secrets

CONTENU = """
# commentaire
BRAVE_API_KEY=abc123
AUTRE="avec des guillemets"
ligne-sans-egal
VIDE=
"""


def _fichier(tmp_path):
    chemin = tmp_path / "secrets.env"
    chemin.write_text(CONTENU, encoding="utf-8")
    return chemin


def test_chargement(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("AUTRE", raising=False)
    charges = charger_secrets(_fichier(tmp_path))

    assert set(charges) == {"BRAVE_API_KEY", "AUTRE"}
    assert os.environ["BRAVE_API_KEY"] == "abc123"
    assert os.environ["AUTRE"] == "avec des guillemets"


def test_l_environnement_a_la_priorite(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "deja-definie")
    charger_secrets(_fichier(tmp_path))
    assert os.environ["BRAVE_API_KEY"] == "deja-definie"


def test_fichier_absent(tmp_path):
    assert charger_secrets(tmp_path / "rien.env") == []


def test_aucune_valeur_dans_le_retour(tmp_path, monkeypatch):
    """Le retour sert aux logs : il ne doit contenir que des noms."""
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    charges = charger_secrets(_fichier(tmp_path))
    assert not any("abc123" in c for c in charges)
