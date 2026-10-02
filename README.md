# Cockpit TR

Tableau de bord personnel et **local** pour suivre un portefeuille Trade Republic
(compte-titres et PEA) : positions, lignes soldées, frais, ordres par trimestre,
snapshots datés.

L'application tourne sur votre ordinateur et n'écoute que sur `127.0.0.1`. Elle
ne se connecte pas à Trade Republic, ne demande aucun identifiant et ne passe
aucun ordre. Sa seule sortie vers Internet sert à récupérer des cours : elle
envoie des codes ISIN et des symboles, et le nom d'un titre quand vous lui
demandez de le chercher par nom ; jamais de quantités ni de montants.

> Outil personnel, non affilié à Trade Republic. Ce n'est pas un conseil en
> investissement.

## État du projet

| Phase | Contenu | État |
| --- | --- | --- |
| V0 | Import de l'export CSV, base SQLite, calculs, tableau de bord, snapshots | fait |
| V0 (suite) | Cours par ISIN, graphiques par titre, mini-courbes, courbe de la valeur du portefeuille | fait |
| V1 | Règles du portefeuille, statut de conformité daté, feuille de route, or physique | à venir |
| V2 | Assistant et routines d'analyse (la fiche du jour existe déjà, voir `fiches/`) | en cours |
| V3 | Tickets d'ordre : préparés et contrôlés ici, passés dans l'app Trade Republic | à venir |

Pas de connexion programmatique à Trade Republic : son contrat client interdit
l'accès par un programme qu'il ne fournit pas. Les transactions viennent de
l'export CSV officiel.

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

## Cours et graphiques

Les cours viennent de Yahoo Finance, recherchés par code ISIN. C'est une source
gratuite et **non officielle** : Yahoo ne publie pas cette interface, peut la
modifier, la ralentir ou la refuser. L'application reste donc modeste (une
requête à la fois, espacées, jamais plus d'une par minute et par titre) et
continue de fonctionner sans elle : un cours se saisit toujours à la main.

| Marché | Fraîcheur des cours gratuits |
| --- | --- |
| Nasdaq, NYSE, Copenhague | temps réel |
| Euronext Paris et Amsterdam, bourses allemandes, Hong Kong | différé de 15 minutes |
| Londres | différé de 20 minutes |

Source : [tableau des places de Yahoo Finance](https://help.yahoo.com/kb/SLN2310.html).
Les cours en devise sont convertis en euros au taux du moment (du jour, pour
l'historique).

```powershell
uv run cockpit cours                # cours des titres détenus, avec les erreurs éventuelles
uv run cockpit cours --historique   # historique quotidien de tous les titres déjà détenus
```

Trois visuels en découlent :

- **une page par titre** (clic sur son nom dans le portefeuille) : la séance du
  jour, puis de 5 jours à tout l'historique ;
- **une mini-courbe des 30 derniers jours** sur chaque ligne du portefeuille ;
- **la courbe de la valeur du portefeuille** face au capital net engagé, sur
  l'accueil, une fois l'historique chargé.

La recherche par ISIN de Yahoo a des trous (trois titres sur 47 au premier
essai). Dans la page « Données », « Proposer » cherche alors par nom et affiche
les cotations trouvées avec leur cours : c'est vous qui choisissez, car Yahoo
n'indique pas l'ISIN et une recherche par nom peut renvoyer une autre classe
d'action. Si un titre n'est pas sur la bonne place, son symbole Yahoo se saisit
au même endroit (par exemple `AI.PA`).

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
- **Espèces** : estimation à partir des transactions.
- **Valeur dans le temps** : quantité détenue chaque jour, multipliée par le
  dernier cours connu en euros. Les quantités d'avant un fractionnement sont
  retraitées, comme le sont les historiques de cours publiés. Une ligne sans
  cours connu est comptée à son prix de revient, et ce montant est indiqué.

Un type de transaction inconnu est conservé et signalé à l'import, mais ignoré
dans les calculs : l'outil ne devine pas.

## Développement

```powershell
uv run pytest                 # tests (données inventées)
uv run ruff check .           # style
uv run cockpit serve --no-open
cd frontend; npm run dev      # interface avec rechargement à chaud
```

Structure : `src/cockpit` (import, calculs, API FastAPI), `src/cockpit/market`
(source de cours, derrière une interface remplaçable), `frontend` (React,
TypeScript, Vite, Tailwind, Lightweight Charts), `tests`.
