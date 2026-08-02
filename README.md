# leadgen

**Constituer un fichier de prospection B2B à partir des registres publics,
légalement, sans acheter de base de données.**

leadgen part de sources ouvertes françaises, retrouve le site de chaque
structure, y récupère l'adresse de contact **déjà publiée**, note le lead selon
votre cible, et exporte le tout dans un tableur.

Il fait partie d'une paire :

| | |
|---|---|
| **leadgen** *(ici)* | trouve et qualifie les contacts |
| **[mailing](https://github.com/Maxyull/mailing)** | rédige, envoie, relance, trie les réponses |

Chacun s'utilise seul. Ensemble, ils partagent une liste d'opposition unique,
ce qui fait qu'une désinscription obtenue à l'envoi protège aussi les collectes
suivantes. Voir [Utiliser les deux ensemble](#utiliser-les-deux-ensemble).

---

## En quoi ça consiste

```
SIRENE + OpenStreetMap  →  site officiel  →  adresse publiée  →  score  →  export .xlsx
```

| Étape | Commande | Ce qui se passe |
|---|---|---|
| 1. Collecter | `collecte` | interroge **SIRENE** (open data, sans clé) et **OpenStreetMap** selon vos critères : activité, effectif, département |
| 2. Enrichir | `enrichir` | retrouve le site officiel, suit les vrais liens de contact de la page d'accueil, en extrait les adresses publiées |
| 3. Qualifier | *(automatique)* | note chaque lead de 0 à 100 : type d'adresse, taille, signaux relevés sur le site |
| 4. Vérifier | `verifier` | teste le domaine de chaque adresse (MX puis A) et écarte ce qui ne peut plus recevoir |
| 5. Exporter | `exporter` | produit un `.xlsx` trié, prêt à relire |

L'état vit dans une base SQLite : une interruption ne fait rien perdre, on
relance et ça reprend où c'était.

`--departements tous` couvre les 101 départements. Overpass bascule alors sur
une maille région, 18 requêtes au lieu de 101 : c'est un service bénévole, on ne
le martèle pas.

---

## Le cadre juridique, et pourquoi il est dans le code

En France, la prospection B2B par courriel ne demande pas de consentement
préalable, à trois conditions : l'adresse est **professionnelle**, le message
est **en rapport avec la fonction** de la personne, et il existe un **moyen
simple de s'y opposer**.

Ces conditions ne sont pas des recommandations dans un fichier de documentation,
elles sont appliquées par le programme. Ce ne sont pas des options désactivées
par défaut, ce sont des refus :

| | |
|---|---|
| ✅ | SIRENE (open data Etalab) et OpenStreetMap (ODbL) |
| ✅ | site officiel de la structure : accueil et les pages de contact qu'il indique lui-même |
| ✅ | boîtes de **fonction** : `contact@`, `cabinet@`, `dpo@`, `rh@`… |
| ❌ | **réseaux sociaux** — interdit par leurs conditions d'utilisation, sanctionné par la CNIL |
| ❌ | tout contenu derrière un login |
| ❌ | adresses **nominatives** (`prenom.nom@`) — données personnelles, écartées par défaut |
| ❌ | adresses techniques (`noreply@`, `postmaster@`, `abuse@`) — souvent des pièges à spam |
| ❌ | adresses **devinées** (`prenom.nom@domaine` fabriqué) — rebonds garantis, et traitement sans source |

`robots.txt` est respecté, une seule requête à la fois par domaine, et le robot
s'annonce avec une identité joignable pour qu'un webmaster puisse demander un
retrait.

**La liste d'opposition est définitive.** Une adresse qui s'y trouve n'est même
pas stockée à la collecte, et rien ne l'en retire.

Un journal horodaté enregistre chaque action : quelle donnée, d'où elle vient,
quand, pourquoi. C'est ce qui se montre en cas de réclamation.

---

## Installation

Python 3.10 ou plus.

```bash
git clone https://github.com/Maxyull/leadgen.git
cd leadgen
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS : source .venv/bin/activate
pip install -r requirements.txt
```

Vérifier que tout fonctionne :

```bash
python -m pytest
```

136 tests, aucun accès réseau : les réponses HTTP sont des doublures.

### Régler votre cible

Tout est dans `config/icp.json` : segments visés (codes NAF), tranches
d'effectif, mots-clés qui font monter le score. Le fichier livré est un exemple,
adaptez-le à votre marché.

⚠️ Le score est figé au moment de la collecte. Après avoir modifié `icp.json`,
lancez `python -m leadgen renoter`, sinon la base porte deux barèmes en même
temps.

### Deux réglages optionnels

Créez `../secrets/leadgen.env`, à côté du dépôt et non dedans :

```
# Identite annoncee aux sites visites. Mettez une adresse ou l'on peut
# vraiment vous joindre : c'est ce qui permet de demander un retrait.
LEADGEN_USER_AGENT=VotreBot/1.0 (+https://votre-site.fr ; prospection B2B ; desinscription : contact@votre-site.fr)

# Optionnel, mais c'est le vrai levier de rendement.
BRAVE_API_KEY=...
```

Sans clé de recherche, leadgen devine le nom de domaine à partir du nom de la
structure : ça marche environ une fois sur sept sur les cabinets nommés d'après
leurs associés. Avec Brave, il retrouve le site presque à chaque fois. L'offre
gratuite (2000 requêtes par mois) suffit largement.

---

## Utilisation

```bash
python -m leadgen collecte --segments notaires,avocats --departements 44,85 --limite 300
python -m leadgen enrichir --limite 150 --moteur brave
python -m leadgen verifier
python -m leadgen exporter --out exports/leads.xlsx --score-min 60
python -m leadgen stats
```

Retirer quelqu'un, définitivement :

```bash
python -m leadgen desinscrire contact@exemple.fr --motif "demande par mail"
```

`enrichir` traite d'abord ce qui rapporte : les structures dont le site est déjà
connu, puis les effectifs les plus intéressants. On peut donc enchaîner des lots
et s'arrêter quand ça suffit.

**À quoi s'attendre.** La collecte est rapide, quelques dizaines de milliers de
structures en une demi-heure. L'enrichissement est le goulot, environ 8 secondes
par structure. Et beaucoup de petits cabinets n'affichent qu'un formulaire de
contact, sans adresse : c'est un plafond structurel, pas un défaut de l'outil.

---

## Utiliser les deux ensemble

[mailing](https://github.com/Maxyull/mailing) lit la base de leadgen **en lecture
seule** et partage sa liste d'opposition. C'est ce partage qui compte : sans lui,
la personne qui a répondu « stop » à un envoi serait recontactée au lot suivant,
sur une autre adresse du même cabinet.

Posez simplement les deux dépôts côte à côte :

```
votre-dossier/
├── leadgen/     ← collecte et qualifie
├── mailing/     ← rédige, envoie, relance, trie les réponses
└── secrets/     ← vos clés, hors des deux dépôts
```

`mailing` trouvera `../leadgen/data/leads.db` tout seul, et écrira dans la même
`../leadgen/data/liste-opposition.txt`.

---

## Ce que le dépôt ne contient pas

Aucune donnée collectée, aucune adresse réelle, aucun secret. `data/` et
`exports/` sont exclus : ils contiennent des données personnelles.

## Licence

[MIT](LICENSE). Faites-en ce que vous voulez, y compris commercialement, en
gardant la mention de copyright. Le logiciel est fourni sans garantie.

⚠️ La licence couvre le code, pas votre usage : ce que vous collectez et à qui
vous écrivez reste votre responsabilité, sous le droit qui s'applique chez vous.
