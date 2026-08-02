"""Ligne de commande du pipeline de prospection.

    python -m leadgen collecte  --segments avocats,notaires --sources sirene,osm \
                                --departements tous --limite 300
    python -m leadgen enrichir  --limite 200 --moteur brave
    python -m leadgen verifier
    python -m leadgen exporter  --out exports/leads-aout.xlsx --score-min 60
    python -m leadgen stats
    python -m leadgen desinscrire contact@cabinet.fr
"""

from __future__ import annotations

import argparse
import itertools
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from . import config as cfg
from . import geo
from .compliance import (
    user_agent,
    CacheRobots,
    LimiteurDebit,
    ListeOpposition,
    classer_email,
    email_exploitable,
)
from .enrich import emails as mod_emails
from .enrich import recherche as mod_recherche
from .enrich import signaux as mod_signaux
from .enrich import website as mod_site
from .export import exporter
from .models import Entreprise, Lead
from .qualify import SEUIL_QUALIFIE, noter
from .sources import osm, sirene
from .storage import Base

log = logging.getLogger("leadgen")

# Moteurs de recherche externes -> pause imposee entre deux requetes.
# Brave (offre gratuite) plafonne a 1 requete/seconde ; Google est plus souple
# mais son quota est journalier (100/jour), pas mensuel.
MOTEURS_EXTERNES = {"brave": 1.1, "google": 0.3}


def _liste(valeur: str) -> list[str]:
    return [v.strip() for v in (valeur or "").split(",") if v.strip()]


def _creer_lead(base, opposition, priorite, entreprise, email, source_url,
                analyse=None) -> bool:
    """Note puis enregistre un contact. False s'il est ecarte ou deja connu."""
    if opposition.contient(email):
        log.info("  %s : liste d'opposition, ignore", email)
        return False
    score, raisons = noter(entreprise, email, priorite,
                           site_trouve=bool(entreprise.site))
    analyse = analyse or {}
    lead = Lead(
        siren=entreprise.siren, nom=entreprise.nom, segment=entreprise.segment,
        email=email, type_email=classer_email(email), site=entreprise.site or "",
        source_url=source_url, ville=entreprise.ville,
        code_postal=entreprise.code_postal, departement=entreprise.departement,
        tranche_effectif=entreprise.tranche_effectif, naf=entreprise.naf,
        source=entreprise.source, score=score, raisons=raisons,
        titre=analyse.get("titre", ""), accroche=analyse.get("accroche", ""),
        signaux=", ".join(analyse.get("signaux") or ()),
        angle=mod_signaux.accroche_mail(analyse),
    )
    if base.enregistrer_lead(lead):
        log.info("  + %s (score %d)", email, score)
        return True
    return False


def _client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": user_agent(), "Accept-Language": "fr-FR,fr;q=0.9"},
        follow_redirects=True,
        verify=True,
    )


# --------------------------------------------------------------------------
def cmd_collecte(args) -> int:
    icp = cfg.charger_icp(args.icp)
    base = Base(args.base)
    opposition = ListeOpposition(args.opposition)
    segments = icp.resoudre(_liste(args.segments))
    sources = _liste(args.sources) or ["sirene"]
    effectifs = _liste(args.effectifs) or icp.effectifs
    departements = geo.resoudre_departements(_liste(args.departements))
    zones_osm, niveau_osm = geo.zones_osm(departements)
    nouvelles = 0
    contacts = 0

    with _client() as client:
        for segment in segments:
            cle = segment["cle"]
            if "sirene" in sources:
                for naf in segment.get("naf", []):
                    for dep in departements or [""]:
                        try:
                            for entreprise in sirene.rechercher(
                                client, naf, cle, departement=dep,
                                region=args.region, effectifs=effectifs,
                                limite=args.limite,
                                siege_strict=not args.siege_large,
                                recherche_texte=segment.get("q", ""),
                            ):
                                if base.enregistrer_entreprise(entreprise):
                                    nouvelles += 1
                        except Exception as exc:
                            log.error("SIRENE %s dep %s : %s", naf, dep or "-", exc)

            if "osm" in sources and segment.get("osm"):
                if not zones_osm:
                    log.warning("OSM ignore pour %s : --departements est requis", cle)
                for zone in zones_osm:
                    try:
                        for entreprise in osm.rechercher(
                            client, segment["osm"], cle, zone,
                            limite=args.limite, niveau=niveau_osm,
                        ):
                            if base.enregistrer_entreprise(entreprise):
                                nouvelles += 1
                            # OpenStreetMap publie parfois directement l'adresse
                            if entreprise.email_public and email_exploitable(
                                entreprise.email_public
                            ):
                                if _creer_lead(base, opposition, icp.priorite(cle),
                                               entreprise, entreprise.email_public,
                                               f"https://www.openstreetmap.org/"
                                               f"{entreprise.siren[4:]}"):
                                    contacts += 1
                    except Exception as exc:
                        log.error("OSM %s %s %s : %s", cle, niveau_osm, zone, exc)

    base.journaliser("collecte", ",".join(s["cle"] for s in segments),
                     {"nouvelles": nouvelles, "contacts": contacts,
                      "sources": sources, "departements": departements})
    stats = base.stats()
    print(f"{nouvelles} structures nouvelles, {contacts} contacts directs "
          f"({stats['entreprises']} en base, {stats['a_enrichir']} a enrichir)")
    base.fermer()
    return 0


def cmd_enrichir(args) -> int:
    icp = cfg.charger_icp(args.icp)
    base = Base(args.base)
    opposition = ListeOpposition(args.opposition)
    limiteur = LimiteurDebit(delai=args.delai)
    entreprises = base.entreprises_a_enrichir(args.limite, _liste(args.segments))
    if not entreprises:
        print("Rien a enrichir. Lance d'abord `collecte`.")
        base.fermer()
        return 0

    sites, contacts = 0, 0
    compteur_moteur = itertools.count()
    verrou_moteur = threading.Lock()

    def travailler(entreprise):
        """Reseau uniquement : aucune ecriture en base depuis les threads."""
        site = entreprise.site
        if not site and args.moteur != "aucun":
            # 1) la devinette : gratuite, on l'epuise d'abord
            site = mod_site.trouver_site(
                client, entreprise, robots, limiteur,
                candidats=mod_recherche.candidats_devines(entreprise),
            )
        if not site and args.moteur in MOTEURS_EXTERNES:
            # 2) le moteur : quota limite, seulement en secours, et serialise
            #    (l'offre gratuite de Brave plafonne a 1 requete/seconde)
            with verrou_moteur:
                if next(compteur_moteur) < args.budget_moteur:
                    urls = mod_recherche.candidats(client, entreprise, args.moteur)
                    time.sleep(MOTEURS_EXTERNES[args.moteur])
                else:
                    urls = []
            if urls:
                site = mod_site.trouver_site(client, entreprise, robots,
                                             limiteur, candidats=urls)
        if not site:
            return entreprise, None, None
        entreprise.site = site
        recolte = mod_emails.collecter_emails(
            client, site, robots, limiteur,
            autoriser_nominatif=args.nominatifs,
            max_pages=args.pages_par_site,
        )
        return entreprise, site, recolte

    with _client() as client:
        robots = CacheRobots(
            fetch=lambda u: client.get(u, timeout=5).text, actif=not args.ignorer_robots
        )
        with ThreadPoolExecutor(max_workers=args.paralleles) as pool:
            taches = [pool.submit(travailler, e) for e in entreprises]
            for i, tache in enumerate(as_completed(taches), 1):
                try:
                    entreprise, site, recolte = tache.result()
                except Exception as exc:
                    log.error("echec d'enrichissement : %s", exc)
                    continue
                log.info("[%d/%d] %s (%s)%s", i, len(entreprises),
                         entreprise.nom[:45], entreprise.ville,
                         "" if site else " - sans site")
                if not site:
                    # on note le moteur : un moteur plus puissant pourra
                    # reprendre cette structure plus tard (`retenter`)
                    base.maj_site(entreprise.siren, None, "introuvable",
                                  moteur=args.moteur)
                    continue
                sites += 1
                base.maj_site(entreprise.siren, site, "traite")
                for email, source in recolte.emails[: args.emails_par_site]:
                    if _creer_lead(base, opposition, icp.priorite(entreprise.segment),
                                   entreprise, email, source, recolte.analyse):
                        contacts += 1

    base.journaliser("enrichissement", "", {"sites": sites, "leads": contacts})
    print(f"{sites} sites verifies, {contacts} contacts nouveaux")
    base.fermer()
    return 0


def cmd_exporter(args) -> int:
    base = Base(args.base)
    opposition = ListeOpposition(args.opposition)
    lignes = base.leads(score_min=args.score_min, segments=_liste(args.segments),
                        limite=args.limite,
                        statut=None if args.reexporter else "nouveau")
    retenues = [l for l in lignes if not opposition.contient(l["email"])]
    ecartees = len(lignes) - len(retenues)
    if not retenues:
        print("Aucun lead a exporter avec ces criteres.")
        base.fermer()
        return 0

    chemin = Path(args.out)
    n = exporter(retenues, chemin)
    if not args.reexporter:
        base.marquer_statut([l["email"] for l in retenues], "exporte")
    base.journaliser("export", str(chemin), {"lignes": n, "score_min": args.score_min})
    print(f"{n} leads -> {chemin}" + (f"  ({ecartees} ecartes : opposition)" if ecartees else ""))
    base.fermer()
    return 0


def cmd_renoter(args) -> int:
    """Reapplique le bareme courant a toute la base (apres edition de l'ICP)."""
    icp = cfg.charger_icp(args.icp)
    base = Base(args.base)

    def calcul(ligne):
        entreprise = Entreprise(
            siren=ligne["siren"] or "", nom=ligne["nom"] or "",
            naf=ligne["naf"] or "", segment=ligne["segment"] or "",
            tranche_effectif=ligne["tranche_effectif"] or "",
            date_creation=ligne["date_creation"] or "",
            site=ligne["site"] or None,
        )
        return noter(entreprise, ligne["email"], icp.priorite(entreprise.segment),
                     site_trouve=bool(ligne["site"]))

    changes = base.renoter(calcul)
    base.journaliser("renotation", "", {"modifies": changes})
    stats = base.stats()
    print(f"{changes} scores modifies, {stats['leads_qualifies']} leads "
          f"qualifies sur {stats['leads']}")
    base.fermer()
    return 0


def cmd_retenter(args) -> int:
    base = Base(args.base)
    remises = base.remettre_en_file(args.quoi, args.moteur)
    base.journaliser("remise-en-file", args.quoi,
                     {"structures": remises, "moteur": args.moteur})
    if args.quoi == "sites-introuvables" and args.moteur and not remises:
        print(f"Rien a reprendre : aucun echec d'un moteur plus faible que "
              f"'{args.moteur}'.")
    else:
        print(f"{remises} structures remises dans la file d'enrichissement")
    base.fermer()
    return 0


def cmd_verifier(args) -> int:
    from .verif import DISPONIBLE, VerificateurDomaine

    if not DISPONIBLE:
        print("dnspython n'est pas installe : pip install dnspython")
        return 1
    base = Base(args.base)
    lignes = base.leads(score_min=args.score_min, statut="nouveau", limite=args.limite)
    verificateur = VerificateurDomaine()
    rejetes = []
    for ligne in lignes:
        if not verificateur.email_recevable(ligne["email"]):
            rejetes.append(ligne["email"])
            log.info("domaine injoignable : %s", ligne["email"])
    base.marquer_statut(rejetes, "rejete")
    base.journaliser("verification", "", {"testes": len(lignes), "rejetes": len(rejetes)})
    print(f"{len(lignes)} adresses testees, {len(rejetes)} rejetees "
          f"(domaine sans MX ni A)")
    base.fermer()
    return 0


def cmd_stats(args) -> int:
    base = Base(args.base)
    s = base.stats()
    print(f"Structures collectees   : {s['entreprises']}")
    print(f"  sites officiels       : {s['sites_trouves']}")
    print(f"  restent a enrichir    : {s['a_enrichir']}")
    print(f"Contacts                : {s['leads']}")
    print(f"  qualifies (>= {SEUIL_QUALIFIE})    : {s['leads_qualifies']}")
    print(f"  deja exportes         : {s['leads_exportes']}")
    print(f"  desinscrits           : {s['desinscrits']}")
    if s["par_segment"]:
        print("Par segment :")
        for segment, n in s["par_segment"].items():
            print(f"  - {segment:24} {n}")
    base.fermer()
    return 0


def cmd_desinscrire(args) -> int:
    base = Base(args.base)
    opposition = ListeOpposition(args.opposition)
    for email in args.emails:
        opposition.ajouter(email, args.motif)
        base.marquer_statut([email.strip().lower()], "desinscrit")
        base.journaliser("desinscription", email, {"motif": args.motif})
        print(f"{email} ajoute a la liste d'opposition")
    base.fermer()
    return 0


# --------------------------------------------------------------------------
def construire_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="leadgen", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default=str(cfg.CHEMIN_BASE), help="fichier SQLite")
    p.add_argument("--icp", default=str(cfg.CHEMIN_ICP), help="profil client ideal")
    p.add_argument("--opposition", default=str(cfg.CHEMIN_OPPOSITION),
                   help="liste d'opposition (desinscrits)")
    p.add_argument("-v", "--verbeux", action="store_true")
    sp = p.add_subparsers(dest="commande", required=True)

    c = sp.add_parser("collecte", help="lister les structures (sources publiques)")
    c.add_argument("--segments", default="tous")
    c.add_argument("--sources", default="sirene",
                   help="sirene (base entreprises) et/ou osm (OpenStreetMap)")
    c.add_argument("--departements", default="",
                   help="ex: 85,44,79 - ou 'tous' pour les 101 departements")
    c.add_argument("--region", default="", help="code region INSEE")
    c.add_argument("--effectifs", default="", help="tranches INSEE, defaut = ICP")
    c.add_argument("--limite", type=int, default=200, help="par NAF et par departement")
    c.add_argument("--siege-large", action="store_true",
                   help="garder les reseaux nationaux ayant une agence locale")
    c.set_defaults(func=cmd_collecte)

    e = sp.add_parser("enrichir", help="site officiel + boite de contact publique")
    e.add_argument("--limite", type=int, default=50, help="structures a traiter")
    e.add_argument("--segments", default="")
    e.add_argument("--delai", type=float, default=1.5,
                   help="secondes entre deux requetes VERS LE MEME domaine")
    e.add_argument("--paralleles", type=int, default=6,
                   help="sites traites en parallele (domaines differents)")
    e.add_argument("--moteur", default="devine",
                   choices=["devine", "brave", "google", "aucun"],
                   help="moteur de secours quand la devinette de domaine echoue : "
                        "brave (2000 requetes/mois) ou google (100/jour)")
    e.add_argument("--budget-moteur", type=int, default=500,
                   help="requetes moteur maximum pour ce lot")
    e.add_argument("--pages-par-site", type=int, default=5)
    e.add_argument("--emails-par-site", type=int, default=2)
    e.add_argument("--nominatifs", action="store_true",
                   help="garder aussi prenom.nom@ (donnee personnelle : a eviter)")
    e.add_argument("--ignorer-robots", action="store_true",
                   help="deconseille, trace dans le journal")
    e.set_defaults(func=cmd_enrichir)

    x = sp.add_parser("exporter", help="produire le fichier de mailing")
    x.add_argument("--out", default=str(cfg.DOSSIER_EXPORTS / "leads.xlsx"))
    x.add_argument("--score-min", type=int, default=SEUIL_QUALIFIE)
    x.add_argument("--segments", default="")
    x.add_argument("--limite", type=int, default=None)
    x.add_argument("--reexporter", action="store_true",
                   help="inclure les leads deja exportes, sans changer leur statut")
    x.set_defaults(func=cmd_exporter)

    n = sp.add_parser("renoter",
                      help="reappliquer le bareme a toute la base (apres edition de l'ICP)")
    n.set_defaults(func=cmd_renoter)

    r = sp.add_parser("retenter", help="remettre en file ce qui avait echoue")
    r.add_argument("--quoi", default="sites-introuvables",
                   choices=["sites-introuvables", "sites-sans-contact"])
    r.add_argument("--moteur", default="",
                   help="ne reprendre que les echecs d'un moteur plus faible "
                        "(ex: --moteur brave reprend ce que la devinette a rate)")
    r.set_defaults(func=cmd_retenter)

    v = sp.add_parser("verifier", help="ecarter les domaines qui ne recoivent pas")
    v.add_argument("--score-min", type=int, default=0)
    v.add_argument("--limite", type=int, default=None)
    v.set_defaults(func=cmd_verifier)

    s = sp.add_parser("stats", help="etat de la base")
    s.set_defaults(func=cmd_stats)

    d = sp.add_parser("desinscrire", help="ajouter une adresse a la liste d'opposition")
    d.add_argument("emails", nargs="+")
    d.add_argument("--motif", default="desinscription")
    d.set_defaults(func=cmd_desinscrire)
    return p


def main(argv=None) -> int:
    args = construire_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbeux else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )
    for nom in cfg.charger_secrets():
        log.debug("secret charge : %s", nom)
    if getattr(args, "ignorer_robots", False):
        log.warning("robots.txt ignore : a n'utiliser que sur tes propres sites")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
