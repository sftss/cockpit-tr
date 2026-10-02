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
- **À regarder** : une phrase factuelle sur un point ouvert, sans consigne
  (400 caractères au plus), ou `null`.
- **Macro** : huit points au plus, chacun avec au moins une source. Décisions de
  banques centrales, inflation, emploi, changes, pétrole, droits de douane,
  semi-conducteurs.
- Aucun mot d'ordre : ni « acheter », ni « vendre », ni objectif de cours.

## Limites

- Les faits sont relevés par une IA dans des sources publiques : une erreur de
  relevé reste possible. Chaque fait renvoie à sa source pour vérification.
- Un fait publié tard le vendredi peut manquer. Ceux du week-end entrent dans
  la veille de la semaine suivante.
- « Rien de notable » veut dire qu'aucun fait de la liste ci-dessus n'a été
  trouvé, pas qu'il ne s'est rien passé.
