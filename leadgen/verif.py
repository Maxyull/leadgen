"""Verification technique des adresses avant envoi.

On ne teste QUE le domaine (enregistrement MX, ou A en repli). C'est ce qui
evite l'essentiel des rebonds : domaine expire, faute de frappe dans les
mentions legales, adresse d'un cabinet ferme.

On ne fait volontairement PAS de verification boite par boite (SMTP `RCPT TO`
sans envoyer) : la plupart des serveurs francais repondent « accepte tout »,
la manoeuvre est detectee comme du spam et fait blacklister l'IP. Le rebond
coute moins cher que la reputation.

dnspython est optionnel : sans lui, `verifier` ne fait rien et le dit.
"""

from __future__ import annotations

import logging

log = logging.getLogger("leadgen.verif")

try:  # pragma: no cover - depend de l'environnement
    import dns.resolver as _resolver
except ImportError:  # pragma: no cover
    _resolver = None

DISPONIBLE = _resolver is not None


class VerificateurDomaine:
    """Cache mutualise : un cabinet et son associe partagent souvent le domaine."""

    def __init__(self, resolveur=None, timeout: float = 5.0):
        self.resolveur = resolveur or _resolver
        self.timeout = timeout
        self.cache: dict[str, bool] = {}

    def _interroger(self, domaine: str, type_enreg: str) -> bool:
        reponse = self.resolveur.resolve(domaine, type_enreg,
                                         lifetime=self.timeout)
        return bool(list(reponse))

    def recevable(self, domaine: str) -> bool:
        """True si le domaine peut recevoir du courrier (MX, sinon A)."""
        domaine = (domaine or "").strip().lower()
        if not domaine:
            return False
        if domaine in self.cache:
            return self.cache[domaine]
        if self.resolveur is None:
            self.cache[domaine] = True      # pas d'outil : on ne rejette rien
            return True
        resultat = False
        for type_enreg in ("MX", "A"):
            try:
                if self._interroger(domaine, type_enreg):
                    resultat = True
                    break
            except Exception as exc:
                log.debug("%s %s : %s", domaine, type_enreg, type(exc).__name__)
        self.cache[domaine] = resultat
        return resultat

    def email_recevable(self, email: str) -> bool:
        _, _, domaine = (email or "").partition("@")
        return self.recevable(domaine)
