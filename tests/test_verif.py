import pytest

from leadgen.verif import VerificateurDomaine


class FauxResolveur:
    """Repond selon une table {(domaine, type): reponse|exception}."""

    def __init__(self, table):
        self.table = table
        self.appels = []

    def resolve(self, domaine, type_enreg, lifetime=None):
        self.appels.append((domaine, type_enreg))
        valeur = self.table.get((domaine, type_enreg))
        if valeur is None:
            raise LookupError("NXDOMAIN")
        return valeur


def test_domaine_avec_mx():
    resolveur = FauxResolveur({("cabinet.fr", "MX"): ["mx1.cabinet.fr"]})
    v = VerificateurDomaine(resolveur)
    assert v.recevable("cabinet.fr") is True
    assert resolveur.appels == [("cabinet.fr", "MX")]


def test_repli_sur_l_enregistrement_a():
    resolveur = FauxResolveur({("cabinet.fr", "A"): ["1.2.3.4"]})
    assert VerificateurDomaine(resolveur).recevable("cabinet.fr") is True


def test_domaine_mort_rejete():
    v = VerificateurDomaine(FauxResolveur({}))
    assert v.recevable("cabinet-ferme.fr") is False
    assert v.email_recevable("contact@cabinet-ferme.fr") is False


def test_cache_un_seul_appel():
    resolveur = FauxResolveur({("cabinet.fr", "MX"): ["mx"]})
    v = VerificateurDomaine(resolveur)
    v.email_recevable("contact@cabinet.fr")
    v.email_recevable("dpo@cabinet.fr")
    assert resolveur.appels == [("cabinet.fr", "MX")]


@pytest.mark.parametrize("email", ["", "pas-d-arobase", "@vide.fr"])
def test_entrees_degenerees(email):
    v = VerificateurDomaine(FauxResolveur({}))
    assert v.email_recevable(email) is False


def test_sans_dnspython_on_ne_rejette_rien():
    v = VerificateurDomaine(resolveur=None)
    v.resolveur = None
    assert v.recevable("cabinet.fr") is True
