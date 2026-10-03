# Veille hebdomadaire

Chaque samedi, un relevé des faits publics de la semaine écoulée pour les
entreprises de `fiches/univers.json`, avec un court contexte macro. Une veille
relève des faits datés, chacun avec sa source. Ce n'est ni une prédiction ni
une recommandation, et elle ne dit rien de la conformité, vérifiée à part.

La veille couvre toute la liste, sans distinction : elle ne sait rien d'un
portefeuille. C'est l'application, sur l'ordinateur de son utilisateur, qui met
en avant les titres détenus ou ciblés.

## Fichiers

Une veille tient en deux fichiers, nommés d'après la semaine ISO de son dernier
jour :

- `AAAA/AAAA-Wnn.json` : les faits, saisis à la main ou par une IA ;
- `AAAA/AAAA-Wnn.md` : la version lisible, écrite par le script à partir du
  fichier JSON. Elle ne se modifie pas à la main.

```
python src/cockpit/veille.py veilles/AAAA/AAAA-Wnn.json
```

Le script vérifie le fichier, puis écrit le `.md`. Il refuse un fichier
incomplet et dit pourquoi. Un test (`tests/test_veille.py`) vérifie que chaque
veille du dépôt passe ces contrôles et que son `.md` est bien celui du script.

## Période

Sept jours, du samedi au vendredi. Une veille écrite un samedi couvre donc la
semaine qui vient de s'achever.

## Format du fichier JSON

```json
{
  "semaine": "2026-W40",
  "du": "2026-09-26",
  "au": "2026-10-02",
  "macro": [
    {
      "sujet": "Taux directeurs",
      "texte": "Ce qui s'est passé, en une ou deux phrases, chiffres à l'appui.",
      "sources": [{"titre": "Banque centrale, communiqué du 1er octobre", "url": "https://…"}]
    }
  ],
  "titres": [
    {
      "nom": "Nom exact de univers.json",
      "isin": "Code ISIN de univers.json",
      "faits": [
        {
          "date": "2026-09-30",
          "texte": "Le fait, en une ou deux phrases, chiffres à l'appui.",
          "source": {"titre": "Communiqué de résultats du 30 septembre", "url": "https://…"}
        }
      ],
      "prochain_rendez_vous": {
        "date": "2026-10-22",
        "objet": "Chiffre d'affaires du troisième trimestre",
        "source": {"titre": "Agenda financier", "url": "https://…"}
      },
      "a_regarder": null
    }
  ]
}
```

Une veille peut se terminer par une `lecture` : une interprétation des faits de
la semaine, tenue à part des faits eux-mêmes.

```json
"lecture": {
  "marche": {
    "hausse": ["Un argument tiré d'un fait relevé plus haut.", "…"],
    "baisse": ["Un argument tiré d'un fait relevé plus haut.", "…"],
    "signaux": [
      {"date": "2026-10-15", "texte": "Ce qui, à venir, ferait pencher d'un côté ou de l'autre."},
      {"date": null, "texte": "Un signal dont la date n'est pas confirmée."}
    ],
    "balance": {"sens": "partagée", "confiance": "faible", "motif": "Pourquoi, en une ou deux phrases."}
  },
  "secteurs": [
    {"secteur": "Santé", "hausse": ["…"], "baisse": ["…"], "signaux": [{"date": null, "texte": "…"}],
     "balance": {"sens": "hausse", "confiance": "faible", "motif": "…"}}
  ]
}
```

## Règles

- **Tous les titres** de `univers.json` figurent dans `titres`, une fois chacun,
  avec le nom et le code ISIN de la liste. Sans fait notable : `"faits": []`.
- **Un fait** est daté dans la période, tient en 500 caractères et porte une
  source avec son titre et son adresse web. Sont relevés : résultats et chiffre
  d'affaires publiés, changement d'objectifs, acquisition ou cession, changement
  de dirigeant, décision d'un régulateur ou d'un tribunal, dividende, rachat
  d'actions, fractionnement, contrat ou produit majeur, incident industriel.
  Ne sont pas relevés : variation de cours seule, avis ou objectif de cours d'un
  analyste, rumeur, article d'opinion.
- **La source** est de préférence le communiqué de l'entreprise ou le document
  réglementaire, sinon une agence ou un journal de référence. Un fait sans
  source lisible n'est pas écrit.
- **Le prochain rendez-vous** (publication de résultats, assemblée, journée
  investisseurs) a une date postérieure à la période et une source. Inconnu ou
  non confirmé : `null`.
- **À regarder** : une phrase factuelle sur un point ouvert et à venir, sans
  consigne (400 caractères au plus), ou `null`. Elle prolonge un fait sourcé de
  la veille, ou cite sa source dans la phrase ; elle ne sert pas à glisser un
  fait antérieur à la période.
- **Macro** : huit points au plus, chacun avec au moins une source. Décisions de
  banques centrales, inflation, emploi, changes, pétrole, droits de douane,
  semi-conducteurs.
- Aucun mot d'ordre : ni « acheter », ni « vendre », ni objectif de cours.

### Lecture de la semaine

- **Ce que c'est** : des scénarios, pas une prédiction. Personne ne sait où va
  un marché ; la lecture dit ce qui pousse d'un côté, ce qui pousse de l'autre,
  et ce qui trancherait.
- **Deux côtés, toujours** : de 1 à 4 arguments à la hausse et de 1 à 4 à la
  baisse, 300 caractères au plus chacun. Chaque argument part d'un fait relevé
  dans la veille (contexte ou titres), ou d'un mécanisme économique dit
  simplement. Aucun chiffre qui ne figure pas plus haut avec sa source.
- **Signaux** : de 1 à 4 événements ou publications à venir. Une date n'est
  donnée que si elle est confirmée dans la veille ; sinon `null`.
- **Balance** : `hausse`, `baisse` ou `partagée`, avec une confiance `faible`
  ou `moyenne` et un motif. Il n'existe pas de confiance « forte ». `partagée`
  est la réponse honnête quand rien ne l'emporte nettement.
- **Portée** : le marché dans son ensemble, puis six secteurs au plus parmi
  ceux de `univers.json`, choisis parce que la semaine a apporté des faits sur
  eux. Pas de lecture titre par titre.
- **Interdits** : consigne d'achat ou de vente, objectif de cours, urgence.
  Le script refuse les mots « acheter », « vendre », « renforcer », « alléger »
  et « objectif de cours » dans la lecture.

### Ce que les lectures ont valu

L'application, pas la veille, compare ensuite chaque balance du marché à la
variation d'un indice mondial sur la semaine suivante. Une veille ne se note
pas elle-même et ne revient pas sur ses lectures passées.

## Limites

- Les faits sont relevés par une IA dans des sources publiques : une erreur de
  relevé reste possible. Chaque fait renvoie à sa source pour vérification.
- Un fait publié tard le vendredi peut manquer. Ceux du week-end entrent dans
  la veille de la semaine suivante.
- « Rien de notable » veut dire qu'aucun fait de la liste ci-dessus n'a été
  trouvé, pas qu'il ne s'est rien passé.
- La lecture de la semaine est une opinion rédigée par une IA à partir d'une
  semaine de faits. Sa balance se trompera régulièrement, et elle ne tient
  compte ni de la valorisation des titres ni de la situation de qui la lit. Ce
  n'est pas un conseil en investissement.
