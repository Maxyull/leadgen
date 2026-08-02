"""Stockage SQLite : reprise apres interruption, dedoublonnage, journal RGPD.

Le journal (`journal`) sert de registre de traitement : quelle donnee, d'ou
elle vient, quand, pourquoi. C'est ce qu'on montre en cas de reclamation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .models import Entreprise, Lead

SCHEMA = """
CREATE TABLE IF NOT EXISTS entreprises (
    siren            TEXT PRIMARY KEY,
    nom              TEXT NOT NULL,
    naf              TEXT,
    segment          TEXT,
    code_postal      TEXT,
    ville            TEXT,
    departement      TEXT,
    tranche_effectif TEXT,
    categorie        TEXT,
    date_creation    TEXT,
    adresse          TEXT,
    site             TEXT,
    site_statut      TEXT DEFAULT 'inconnu',
    email_public     TEXT DEFAULT '',
    source           TEXT DEFAULT 'sirene',
    moteur_essaye    TEXT DEFAULT '',
    vu_le            TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    email            TEXT PRIMARY KEY,
    siren            TEXT NOT NULL,
    nom              TEXT,
    segment          TEXT,
    type_email       TEXT,
    site             TEXT,
    source_url       TEXT,
    ville            TEXT,
    code_postal      TEXT,
    departement      TEXT,
    tranche_effectif TEXT,
    naf              TEXT,
    source           TEXT DEFAULT 'sirene',
    titre            TEXT DEFAULT '',
    accroche         TEXT DEFAULT '',
    signaux          TEXT DEFAULT '',
    angle            TEXT DEFAULT '',
    score            INTEGER DEFAULT 0,
    raisons          TEXT,
    statut           TEXT DEFAULT 'nouveau',
    collecte_le      TEXT,
    exporte_le       TEXT,
    FOREIGN KEY (siren) REFERENCES entreprises(siren)
);

CREATE TABLE IF NOT EXISTS journal (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    horodat TEXT NOT NULL,
    action  TEXT NOT NULL,
    cible   TEXT,
    detail  TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_score  ON leads(score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_statut ON leads(statut);
CREATE INDEX IF NOT EXISTS idx_ent_statut   ON entreprises(site_statut);
"""


# Colonnes ajoutees apres la premiere version : appliquees par ALTER TABLE.
COLONNES_AJOUTEES = {
    "entreprises": {
        "email_public": "TEXT DEFAULT ''",
        "source": "TEXT DEFAULT 'sirene'",
        # avec quel moteur on a cherche le site sans le trouver : permet de
        # reprendre plus tard avec un moteur plus puissant au lieu de jeter
        "moteur_essaye": "TEXT DEFAULT ''",
    },
    "leads": {
        "source": "TEXT DEFAULT 'sirene'",
        "titre": "TEXT DEFAULT ''",
        "accroche": "TEXT DEFAULT ''",
        "signaux": "TEXT DEFAULT ''",
        "angle": "TEXT DEFAULT ''",
    },
}


# Un moteur ne reprend que les echecs d'un moteur MOINS puissant que lui.
# '' = ancienne base, anterieure au suivi du moteur.
MOTEURS_PLUS_FAIBLES = {
    "brave": ["", "aucun", "devine"],
    "google": ["", "aucun", "devine"],
    "devine": ["", "aucun"],
}


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Base:
    def __init__(self, chemin: Path | str):
        self.chemin = Path(chemin)
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.chemin, timeout=30)
        self.conn.row_factory = sqlite3.Row
        # WAL : permet de collecter et d'enrichir en meme temps sans
        # « database is locked ». Sans lui, deux commandes en parallele
        # se bloquent mutuellement.
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=30000")
        except sqlite3.Error:      # systeme de fichiers qui ne gere pas le WAL
            pass
        self.conn.executescript(SCHEMA)
        self._migrer()
        self.conn.commit()

    def _migrer(self) -> None:
        """Ajoute les colonnes apparues apres coup sur une base existante.

        `CREATE TABLE IF NOT EXISTS` ne modifie pas une table deja creee : sans
        ca, une base collectee avec une version anterieure devient illisible.
        """
        for table, colonnes in COLONNES_AJOUTEES.items():
            presentes = {
                ligne["name"]
                for ligne in self.conn.execute(f"PRAGMA table_info({table})")
            }
            for nom, definition in colonnes.items():
                if nom not in presentes:
                    self.conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {nom} {definition}"
                    )

    # --- ecriture -------------------------------------------------------
    def enregistrer_entreprise(self, e: Entreprise) -> bool:
        """True si nouvelle, False si deja connue (les champs sont rafraichis)."""
        existe = self.conn.execute(
            "SELECT 1 FROM entreprises WHERE siren = ?", (e.siren,)
        ).fetchone() is not None
        self.conn.execute(
            """INSERT INTO entreprises
               (siren, nom, naf, segment, code_postal, ville, departement,
                tranche_effectif, categorie, date_creation, adresse, site,
                site_statut, email_public, source, vu_le)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(siren) DO UPDATE SET
                   nom=excluded.nom, naf=excluded.naf, segment=excluded.segment,
                   code_postal=excluded.code_postal, ville=excluded.ville,
                   departement=excluded.departement,
                   tranche_effectif=excluded.tranche_effectif,
                   categorie=excluded.categorie, adresse=excluded.adresse,
                   vu_le=excluded.vu_le""",
            (e.siren, e.nom, e.naf, e.segment, e.code_postal, e.ville,
             e.departement, e.tranche_effectif, e.categorie, e.date_creation,
             e.adresse, e.site, e.site_statut, e.email_public, e.source,
             _maintenant()),
        )
        self.conn.commit()
        return not existe

    def maj_site(self, siren: str, site: Optional[str], statut: str,
                 moteur: str = "") -> None:
        self.conn.execute(
            "UPDATE entreprises SET site = ?, site_statut = ?, moteur_essaye = ?"
            " WHERE siren = ?",
            (site, statut, moteur, siren),
        )
        self.conn.commit()

    def remettre_en_file(self, quoi: str, moteur: str = "") -> int:
        """Renvoie dans la file ce qui avait ete abandonne.

        `sites-introuvables` : structures dont le site n'a pas ete trouve,
        limitees a celles cherchees avec un moteur plus faible que `moteur`.
        `sites-sans-contact` : sites explores qui n'ont donne aucune adresse
        (le site a pu changer depuis).
        """
        if quoi == "sites-introuvables":
            sql = "UPDATE entreprises SET site_statut = 'inconnu' WHERE site_statut = 'introuvable'"
            params: list = []
            if moteur:
                faibles = MOTEURS_PLUS_FAIBLES.get(moteur, [])
                if not faibles:
                    return 0
                sql += f" AND moteur_essaye IN ({','.join('?' * len(faibles))})"
                params.extend(faibles)
        elif quoi == "sites-sans-contact":
            sql = ("UPDATE entreprises SET site_statut = 'trouve' "
                   "WHERE site_statut = 'traite' AND siren NOT IN "
                   "(SELECT DISTINCT siren FROM leads)")
            params = []
        else:
            raise ValueError(f"remise en file inconnue : {quoi}")
        curseur = self.conn.execute(sql, params)
        self.conn.commit()
        return curseur.rowcount

    def enregistrer_lead(self, lead: Lead) -> bool:
        """True si le lead est nouveau. Un email deja present n'est pas ecrase."""
        existe = self.conn.execute(
            "SELECT 1 FROM leads WHERE email = ?", (lead.email,)
        ).fetchone() is not None
        if existe:
            return False
        self.conn.execute(
            """INSERT INTO leads
               (email, siren, nom, segment, type_email, site, source_url, ville,
                code_postal, departement, tranche_effectif, naf, source, titre,
                accroche, signaux, angle, score, raisons, statut, collecte_le)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lead.email, lead.siren, lead.nom, lead.segment, lead.type_email,
             lead.site, lead.source_url, lead.ville, lead.code_postal,
             lead.departement, lead.tranche_effectif, lead.naf, lead.source,
             lead.titre, lead.accroche, lead.signaux, lead.angle,
             lead.score, " | ".join(lead.raisons), lead.statut, _maintenant()),
        )
        self.conn.commit()
        return True

    def marquer_statut(self, emails: Iterable[str], statut: str) -> int:
        emails = list(emails)
        if not emails:
            return 0
        horodat = _maintenant() if statut == "exporte" else None
        self.conn.executemany(
            "UPDATE leads SET statut = ?, exporte_le = COALESCE(?, exporte_le) WHERE email = ?",
            [(statut, horodat, e) for e in emails],
        )
        self.conn.commit()
        return len(emails)

    def renoter(self, calcul) -> int:
        """Recalcule le score de tous les leads. Retourne le nombre de changements.

        Necessaire des que le profil client ideal change : sans ca la base
        melange deux baremes et `--score-min` ne veut plus rien dire d'un lot
        a l'autre. `calcul(ligne)` doit retourner (score, raisons).
        """
        lignes = self.conn.execute(
            """SELECT l.email, l.segment, l.site, l.score,
                      e.siren, e.nom, e.naf, e.tranche_effectif, e.date_creation
               FROM leads l LEFT JOIN entreprises e ON e.siren = l.siren"""
        ).fetchall()
        maj = []
        for ligne in lignes:
            score, raisons = calcul(ligne)
            if score != ligne["score"]:
                maj.append((score, " | ".join(raisons), ligne["email"]))
        self.conn.executemany(
            "UPDATE leads SET score = ?, raisons = ? WHERE email = ?", maj)
        self.conn.commit()
        return len(maj)

    def journaliser(self, action: str, cible: str = "", detail=None) -> None:
        self.conn.execute(
            "INSERT INTO journal (horodat, action, cible, detail) VALUES (?,?,?,?)",
            (_maintenant(), action, cible,
             json.dumps(detail, ensure_ascii=False) if detail is not None else None),
        )
        self.conn.commit()

    # --- lecture --------------------------------------------------------
    def entreprises_a_enrichir(self, limite: int = 100, segments=()) -> list[Entreprise]:
        # 'inconnu' = site a chercher, 'trouve' = site connu mais emails pas
        # encore extraits (cas OpenStreetMap, qui fournit deja l'URL).
        sql = "SELECT * FROM entreprises WHERE site_statut IN ('inconnu', 'trouve')"
        params: list = []
        if segments:
            sql += f" AND segment IN ({','.join('?' * len(segments))})"
            params.extend(segments)
        # On traite d'abord ce qui rapporte : site deja connu (OpenStreetMap),
        # puis les effectifs les plus interessants.
        sql += """
            ORDER BY (site IS NOT NULL AND site != '') DESC,
                     CASE tranche_effectif
                         WHEN '12' THEN 0 WHEN '11' THEN 1 WHEN '21' THEN 2
                         WHEN '03' THEN 3 WHEN '22' THEN 4 WHEN '02' THEN 5
                         WHEN '01' THEN 6 ELSE 9 END,
                     vu_le
            LIMIT ?"""
        params.append(limite)
        lignes = self.conn.execute(sql, params).fetchall()
        return [
            Entreprise(
                siren=l["siren"], nom=l["nom"], naf=l["naf"] or "",
                segment=l["segment"] or "", code_postal=l["code_postal"] or "",
                ville=l["ville"] or "", departement=l["departement"] or "",
                tranche_effectif=l["tranche_effectif"] or "",
                categorie=l["categorie"] or "", date_creation=l["date_creation"] or "",
                adresse=l["adresse"] or "", site=l["site"],
                site_statut=l["site_statut"] or "inconnu",
                email_public=l["email_public"] or "",
                source=l["source"] or "sirene",
            )
            # NB : moteur_essaye ne sert qu'au tri en base, pas au traitement
            for l in lignes
        ]

    def leads(self, score_min: int = 0, statut: Optional[str] = None,
              segments=(), limite: Optional[int] = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM leads WHERE score >= ?"
        params: list = [score_min]
        if statut:
            sql += " AND statut = ?"
            params.append(statut)
        if segments:
            sql += f" AND segment IN ({','.join('?' * len(segments))})"
            params.extend(segments)
        sql += " ORDER BY score DESC, nom"
        if limite:
            sql += " LIMIT ?"
            params.append(limite)
        return self.conn.execute(sql, params).fetchall()

    def stats(self) -> dict:
        c = self.conn
        return {
            "entreprises": c.execute("SELECT COUNT(*) FROM entreprises").fetchone()[0],
            "sites_trouves": c.execute(
                "SELECT COUNT(*) FROM entreprises WHERE site IS NOT NULL AND site != ''"
            ).fetchone()[0],
            "a_enrichir": c.execute(
                "SELECT COUNT(*) FROM entreprises WHERE site_statut IN ('inconnu','trouve')"
            ).fetchone()[0],
            "leads": c.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
            "leads_qualifies": c.execute(
                "SELECT COUNT(*) FROM leads WHERE score >= 55").fetchone()[0],
            "leads_exportes": c.execute(
                "SELECT COUNT(*) FROM leads WHERE statut = 'exporte'").fetchone()[0],
            "desinscrits": c.execute(
                "SELECT COUNT(*) FROM leads WHERE statut = 'desinscrit'").fetchone()[0],
            "par_segment": {
                r["segment"]: r["n"] for r in c.execute(
                    "SELECT segment, COUNT(*) n FROM leads GROUP BY segment ORDER BY n DESC")
            },
        }

    def fermer(self) -> None:
        self.conn.close()
