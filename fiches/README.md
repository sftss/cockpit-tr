# Fiches du jour

Une entreprise par jour, tirée dans `univers.json`, passée dans une grille de
qualité sur 20. Les fiches servent à trier des candidats pour la revue
trimestrielle. Ce ne sont ni des prédictions ni des recommandations d'achat, et
elles ne disent rien de la conformité, vérifiée à part.

## Déroulé d'une fiche

1. **Tirage** au hasard parmi les entreprises de `univers.json` qui n'ont pas
   encore de fiche dans le tour en cours. Quand toutes en ont une, un nouveau
   tour commence.
2. **Relevé des chiffres publiés** (communiqués de résultats, données de marché)
   dans un fichier `AAAA/AAAA-MM-JJ-nom.json`, avec les sources et le détail
   des calculs intermédiaires.
3. **Note** : `python src/cockpit/scoring.py fiches/AAAA/AAAA-MM-JJ-nom.json`.
   Le script calcule les ratios et les points. Mêmes chiffres, même note.
4. **Fiche lisible** `AAAA/AAAA-MM-JJ-nom.md` : la note et le tableau du script,
   recopiés tels quels, puis ce qui porte la note, un scénario haussier, un
   scénario baissier, la sensibilité de la note et les sources.

Un test (`tests/test_scoring.py`) vérifie que chaque fiche affiche bien la note
et le tableau que le barème donne à ses chiffres.

## Barème

| Critère | Points | Règle |
| --- | --- | --- |
| Croissance du chiffre d'affaires, par an sur 4 exercices | 3 | ≥ 10 % : 3 · 5 à 10 % : 2 · 0 à 5 % : 1 · en baisse : 0 |
| Marge nette, 12 derniers mois | 3 | ≥ 20 % : 3 · ≥ 10 % : 2 · ≥ 5 % : 1 · sinon 0 ; seuils divisés par deux pour les produits physiques |
| Dette nette / EBITDA, 12 derniers mois | 3 | < 2 ou trésorerie nette : 3 · 2 à 3 : 1 · ≥ 3 : 0 |
| Croissance du cash-flow libre, par an sur 4 exercices | 3 | ≥ 10 % : 3 · 0 à 10 % : 2 · en baisse ou irrégulier : 1 · négatif au dernier exercice : 0 |
| ROIC = résultat opérationnel × (1 − taux d'impôt) / (capitaux propres + dette nette) | 4 | ≥ 20 % : 4 · ≥ 15 % : 3 · ≥ 10 % : 2 · ≥ 5 % : 1 · sinon 0 |
| PER, 12 derniers mois | 2 | < 25 : 2 · 25 à 35 : 1 · ≥ 35 ou bénéfice négatif : 0 |
| Taux de distribution | 2 | ≤ 60 % : 2 · 60 à 80 % : 1 · > 80 % : 0 · pas de dividende : 1 |

Les seuils viennent de la méthode AQRP (cinq ratios de base, valorisation,
distribution). Les points par palier sont un choix de ce projet.

| Note | Libellé |
| --- | --- |
| 15 et plus | à approfondir |
| 12 à moins de 15 | à surveiller |
| moins de 12 | écarté |

Un critère dont les chiffres manquent est laissé de côté et la note est ramenée
sur 20 ; en dessous de cinq critères, l'entreprise n'est pas notée.

## Limites

- Les chiffres sont relevés à la main ou par une IA dans des communiqués : une
  erreur de relevé fausse la note. Les sources sont dans chaque fiche.
- Les seuils créent des effets de palier : chaque fiche indique ce qui ferait
  basculer sa note.
- La grille pénalise les activités lourdes en capital (énergie, infrastructures)
  et ne convient pas aux sociétés financières.
