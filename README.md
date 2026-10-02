# Cockpit TR

Tableau de bord personnel et **local** pour suivre un portefeuille Trade Republic
(compte-titres et PEA) : positions, lignes soldées, frais, ordres par trimestre,
snapshots datés.

L'application tourne sur votre ordinateur et n'écoute que sur `127.0.0.1`. Elle
n'envoie aucune donnée à l'extérieur et ne passe aucun ordre.

> Outil personnel, non affilié à Trade Republic. Ce n'est pas un conseil en
> investissement.

## État du projet

| Phase | Contenu | État |
| --- | --- | --- |
| V0 | Import de l'export CSV, base SQLite, calculs, tableau de bord, snapshots | fait |
| V0 (suite) | Connexion Trade Republic en lecture (positions, cours, espèces) | à venir |
| V1 | Règles du portefeuille, statut de conformité daté, feuille de route, or physique | à venir |
| V2 | Assistant et routines d'analyse | à venir |
| V3 | Tickets d'ordre : préparés et contrôlés ici, passés dans l'app Trade Republic | à venir |

## Ce dépôt est public : aucune donnée personnelle ici

| Dans le dépôt | Uniquement sur votre ordinateur |
| --- | --- |
| Le code et ses tests (données inventées) | La base SQLite : transactions, positions, montants |
| | Les exports CSV et les classeurs |
| | Les identifiants et les clés d'API |

Deux garde-fous : le `.gitignore` écarte les fichiers de données, et un test
(`tests/test_repo_hygiene.py`) échoue si git suit un CSV, un classeur, une base
ou un fichier de secrets.

## Installation (Windows)

Deux outils sont nécessaires : [uv](https://docs.astral.sh/uv/) (il installe
Python tout seul) et [Node.js](https://nodejs.org/) 22 ou plus récent.

```powershell
winget install astral-sh.uv
winget install OpenJS.NodeJS.LTS
git clone https://github.com/sftss/cockpit-tr.git
cd cockpit-tr
```

## Utilisation

```powershell
# 1. Importer l'export de transactions (app Trade Republic, export CSV)
uv run cockpit import "C:\chemin\vers\transactions.csv"

# 2. Lancer le tableau de bord (construit l'interface, puis ouvre le navigateur)
.\scripts\start.ps1
```

L'import peut aussi se faire depuis la page « Données » du tableau de bord.
Réimporter un export plus récent n'ajoute que les nouvelles lignes.

Sans le script :

```powershell
cd frontend; npm ci; npm run build; cd ..
uv run cockpit serve          # http://127.0.0.1:8765
uv run cockpit report         # le même résumé, dans le terminal
```

## Où sont mes données

Dans `%LOCALAPPDATA%\cockpit-tr\cockpit.db` (un seul fichier). Le sauvegarder
revient à le copier. La variable d'environnement `COCKPIT_DATA_DIR` change
l'emplacement.

## Comment les chiffres sont calculés

Tout est recalculé à partir des transactions importées
(`src/cockpit/portfolio.py`).

- **Ligne** : un titre dans un compte.
- **Prix de revient** : au coût moyen. Une vente libère le coût moyen des
  titres vendus ; un fractionnement ou une attribution gratuite change la
  quantité, pas le coût.
- **Ligne soldée** : sa quantité est revenue à zéro. Résultat brut = vendu −
  acheté ; résultat net = brut − frais d'ordre. Les taxes sur transactions sont
  affichées à part.
- **Ordre manuel** : un achat ou une vente qui a payé des frais. Les exécutions
  du plan d'épargne et les arrondis sont gratuits et ne sont pas comptés.
- **Capital net apporté** : versements (avant frais de rechargement) moins
  dépenses par carte, le compte servant aussi de compte courant.
- **Capital net engagé** d'un compte : payé en achats moins reçu en ventes.
  La performance compare la valeur à ce capital.
- **Espèces** : estimation à partir des transactions, à confirmer par la future
  synchro.
- **Cours** : saisis à la main dans la page « Portefeuille » pour l'instant.

Un type de transaction inconnu est conservé et signalé à l'import, mais ignoré
dans les calculs : l'outil ne devine pas.

## Développement

```powershell
uv run pytest                 # tests (données inventées)
uv run ruff check .           # style
uv run cockpit serve --no-open
cd frontend; npm run dev      # interface avec rechargement à chaud
```

Structure : `src/cockpit` (import, calculs, API FastAPI), `frontend` (React,
TypeScript, Vite, Tailwind), `tests`.
