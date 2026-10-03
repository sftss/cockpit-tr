# Cockpit TR

Tableau de bord personnel et **local** pour suivre un portefeuille Trade Republic
(compte-titres et PEA) : positions, lignes soldées, frais, ordres par trimestre,
snapshots datés.

L'application tourne sur votre ordinateur et n'écoute que sur `127.0.0.1`. Elle
ne se connecte pas à Trade Republic, ne demande aucun identifiant et ne passe
aucun ordre. Elle sort vers Internet pour deux choses :

- **récupérer des cours** : elle envoie des codes ISIN et des symboles, et le
  nom d'un titre quand vous lui demandez de le chercher par nom ; jamais de
  quantités ni de montants ;
- **l'assistant**, seulement si vous enregistrez une clé d'API : chaque question
  envoie à l'API d'Anthropic les données de portefeuille utiles à la réponse.

> Outil personnel, non affilié à Trade Republic. Ce n'est pas un conseil en
> investissement.

## État du projet

| Phase | Contenu | État |
| --- | --- | --- |
| V0 | Import de l'export CSV, base SQLite, calculs, tableau de bord, snapshots | fait |
| V0 (suite) | Cours par ISIN, graphiques par titre, mini-courbes, courbe de la valeur du portefeuille | fait |
| V1 | Règles du portefeuille, Halalitude datée, feuille de route, or physique | fait |
| V2 | Assistant (chat, journal de décisions), veille hebdomadaire (`veilles/`), fiche du jour (`fiches/`), revue trimestrielle | fait |
| Graphiques | Chandeliers, volume, moyennes mobiles et ordres sur la page d'un titre ; carte du portefeuille ; performance comparée ; répartition | fait |
| V3 | Tickets d'ordre : préparés et contrôlés ici, passés dans l'app Trade Republic | à venir |

Pas de connexion programmatique à Trade Republic : son contrat client interdit
l'accès par un programme qu'il ne fournit pas. Les transactions viennent de
l'export CSV officiel.

## Ce dépôt est public : aucune donnée personnelle ici

| Dans le dépôt | Uniquement sur votre ordinateur |
| --- | --- |
| Le code et ses tests (données inventées) | La base SQLite : transactions, positions, montants |
| | Les exports CSV et les classeurs |
| Les types de règles | Les valeurs des règles, les motifs d'écart, la feuille de route |
| | Les statuts de Halalitude, les lots d'or |
| La consigne générique de l'assistant | Les consignes personnelles, les discussions, le journal de décisions |
| Fiches et veilles sur une liste publique d'entreprises | Lesquelles de ces entreprises sont détenues ou ciblées |
| | La clé d'API (gestionnaire d'identifiants de Windows) |
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

Au lancement, le script fait un `git pull` pour récupérer les fiches, les
veilles et le code fusionné depuis la dernière fois. Hors ligne, il le dit et
lance l'application telle qu'elle est.

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

Ce qui en découle à l'écran :

- **Une page par titre** (clic sur son nom dans le portefeuille ou dans les
  lignes soldées), de la séance du jour à tout l'historique :
  - chandeliers ou courbe, volume en dessous ;
  - moyennes mobiles sur 50 et 200 jours (10 et 40 semaines sur 5 ans) ;
  - vos achats et vos ventes marqués sur le jour de l'ordre, et la liste de
    ces ordres ;
  - pour un titre coté dans une autre devise, le graphique en euros : chaque
    barre est convertie au taux de change de son jour. C'est une
    reconstitution, le titre n'étant pas coté en euros sur cette place ;
  - chiffres clés : fourchettes de la séance et des 52 semaines, volume,
    variation sur 1 mois, 6 mois, 1 an et depuis le 1er janvier.
- **La carte du portefeuille** : une tuile par titre, grande comme son poids,
  colorée selon sa variation (séance, 30 jours, depuis l'achat).
- **La répartition** par compte, type de titre, devise de cotation, pays du
  siège et secteur. Pays et secteur viennent de `fiches/univers.json` ; un
  fonds compte pour un seul bloc.
- **Une mini-courbe des 30 derniers jours** sur chaque ligne du portefeuille.
- **La courbe de la valeur du portefeuille** face au capital net engagé, sur
  l'accueil, une fois l'historique chargé.
- **La performance comparée** à un fonds du portefeuille ou à un indice (MSCI
  World, S&P 500, CAC 40). Les achats et les ventes sont neutralisés jour par
  jour : la courbe mesure l'évolution des titres détenus, pas l'argent ajouté.
  Hors frais d'ordre et dividendes reçus.

Ce que l'application n'a pas, faute de source ou par choix : carnet d'ordres,
flux des transactions du marché, outils de dessin, recherche de titres par
critères, produits à effet de levier, passage d'ordre.

La recherche par ISIN de Yahoo a des trous (trois titres sur 47 au premier
essai). Dans la page « Données », « Proposer » cherche alors par nom et affiche
les cotations trouvées avec leur cours : c'est vous qui choisissez, car Yahoo
n'indique pas l'ISIN et une recherche par nom peut renvoyer une autre classe
d'action. Si un titre n'est pas sur la bonne place, son symbole Yahoo se saisit
au même endroit (par exemple `AI.PA`).

## Règles, Halalitude, feuille de route, or

- **Règles.** Le code connaît des types de règles (ordres manuels par
  trimestre, frais d'ordre, montant minimal d'un achat, pas de nouvelle ligne
  sous une certaine valeur de portefeuille, ventes, lignes soldées,
  rechargements par carte, poids maximal d'une ligne). Leurs valeurs se règlent
  dans la page « Règles », avec une date d'effet ; l'ancienne valeur reste dans
  l'historique. Une règle ne bloque rien : une transaction importée qui s'en
  écarte est listée, et un motif s'écrit à côté. Une transaction n'est comparée
  qu'aux règles en vigueur le jour où elle a été passée.
- **Halalitude.** L'application ne vérifie rien : elle garde le statut relevé à
  la main dans les screeners (halal, douteux ou haram), avec la date de ce
  relevé et une note pour dire lesquels ont été consultés. Au-delà de 90 jours,
  le statut passe « à revérifier ».
- **Feuille de route.** Des cibles, pas des ordres : titre, compte, montant
  prévu, condition d'entrée, thèse. Si une cible porte un cours d'entrée, la
  page le signale quand le cours l'atteint ; rien d'autre ne se passe.
- **Or physique.** Des lots saisis à la main (poids d'or fin, prix payé),
  valorisés au cours mondial de l'or converti en euros, hors prime. L'or est
  compté à part : ni dans les poids, ni dans les règles, ni dans la courbe.
- **Fichier de réglages.** Les valeurs des règles, la feuille de route et les
  consignes de l'assistant s'exportent et s'importent en JSON depuis la page
  « Données ». Ce fichier est personnel : le `.gitignore` l'écarte du dépôt.

## Assistant

Un chat intégré, qui lit les données locales par des outils : positions, lignes
soldées, frais, règles et écarts, Halalitude, feuille de route, transactions,
cours, fiches du jour, veille hebdomadaire, revues trimestrielles, journal de
décisions.

- **Clé d'API.** Elle se crée dans la console Anthropic et se saisit une fois
  dans la page « Assistant ». Elle est rangée dans le gestionnaire
  d'identifiants de Windows ; aucune page ni aucun export ne la réaffiche.
  L'API est facturée à l'usage, séparément d'un abonnement Claude.
- **Ce que l'assistant ne voit pas.** L'or physique, les paiements par carte et
  les coordonnées bancaires ne lui sont jamais transmis.
- **Ce qu'il peut écrire.** Une note dans le journal de décisions et une
  proposition de cible sur la feuille de route (statut « idée », sans montant ni
  cours d'entrée), toutes deux marquées comme venant de lui. Rien d'autre : ni
  règle, ni statut, ni motif.
- **Recherche web.** Un interrupteur dans le chat, éteint par défaut ; les
  sources s'affichent sous la réponse.
- **Coût.** Les tokens et un coût estimé s'affichent sous chaque réponse et par
  mois, face à un budget qui sert de repère sans rien bloquer. Le plafond réel
  se règle dans la console Anthropic.
- **Consignes personnelles.** Vos consignes et documents de référence se
  saisissent dans les réglages de l'assistant, ou s'importent avec le fichier
  de réglages. Le dépôt ne contient qu'une consigne générique.
- **Journal de décisions.** Une page pour noter une décision et son motif ;
  l'assistant le lit.

## Veille hebdomadaire

Chaque samedi matin, une tâche planifiée de Claude relève les faits publics de
la semaine (résultats, annonces, prochains rendez-vous) pour les entreprises de
`fiches/univers.json`, avec un court contexte macro, et les dépose dans
`veilles/`. Chaque fait porte sa date et sa source. Format et règles :
[`veilles/README.md`](veilles/README.md).

La veille couvre toute la liste et ne sait rien du portefeuille. C'est la page
« Veille », sur votre ordinateur, qui met en avant vos lignes et les cibles de
votre feuille de route, puis replie le reste. Les fonds ne sont pas couverts.

Ce sont des faits relevés par une IA : une erreur reste possible, d'où le lien
vers la source à côté de chacun.

La veille se termine par une **lecture de la semaine**, pour le marché puis par
secteur : ce qui pousse à la hausse, ce qui pousse à la baisse, ce qui
trancherait, et une balance (hausse, baisse ou partagée) avec un niveau de
confiance faible ou moyen. C'est une interprétation, tenue à part des faits :
une opinion argumentée qui se trompera régulièrement, pas une prédiction ni un
conseil en investissement. Le script refuse une lecture qui n'argumente qu'un
côté, qui annonce une confiance forte ou qui donne une consigne d'achat ou de
vente.

Pour savoir ce que ces lectures valent, la page compare chaque balance du
marché à ce que le MSCI World a fait, en euros, la semaine suivante. Une
balance « partagée » n'est pas notée. À côté du score figure celui de la
prévision la plus paresseuse, « hausse chaque semaine », sur les mêmes
semaines ; aucun taux de réussite n'est annoncé avant dix lectures notées.

## Revue trimestrielle

La page « Revues » arrête les chiffres d'un trimestre et les garde tels qu'ils
étaient : comptes, performance du trimestre (achats et ventes neutralisés) face
à un fonds du portefeuille, activité face aux règles, écarts et leurs motifs,
frais, lignes ouvertes et soldées, portefeuille et Halalitude, feuille de
route, fiches du trimestre, puis les règles en vigueur pour le trimestre
suivant.

- **L'application calcule, sans IA.** Les mêmes transactions redonnent la même
  revue. « Actualiser les chiffres » la recalcule.
- **Le commentaire de l'assistant est à la demande.** Un bouton lui envoie la
  revue ; sa lecture est gardée avec elle, et la discussion se poursuit dans la
  page « Assistant ». C'est un appel à l'API, compté dans la consommation.
- **Les conclusions sont les vôtres** : un champ libre, conservé quand les
  chiffres sont actualisés.
- **Export en Markdown**, pour l'archiver ou la relire ailleurs. Ce fichier est
  personnel : il ne va pas dans le dépôt.

L'accueil rappelle la revue du dernier trimestre terminé tant qu'elle n'a pas
été faite. Une revue rend compte ; elle ne propose aucun ordre.

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

Les règles du projet, pour une personne comme pour un agent de code, sont dans
[`CLAUDE.md`](CLAUDE.md) : ce qui ne se discute pas, la façon de travailler et
les vérifications à passer avant une demande de fusion.

```powershell
uv run pytest                 # tests (données inventées)
uv run ruff check .           # style
uv run cockpit serve --no-open
cd frontend; npm run dev      # interface avec rechargement à chaud
```

Structure : `src/cockpit` (import, calculs, API FastAPI), `src/cockpit/market`
(source de cours, derrière une interface remplaçable), `frontend` (React,
TypeScript, Vite, Tailwind, Lightweight Charts), `tests`.
