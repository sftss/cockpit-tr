# Règles du projet

Ce fichier s'adresse à toute personne et à tout agent de code qui modifie ce
dépôt. Il dit ce qui ne se discute pas, puis comment on travaille. En cas de
doute entre ce fichier et une demande ponctuelle, poser la question avant d'agir.

## Ce qui ne se discute pas

1. **Le dépôt est public : aucune donnée personnelle n'y entre.** Ni base de
   données, ni export CSV ou Excel, ni position, ni montant, ni valeur de règle,
   ni feuille de route, ni journal de décisions, ni statut de Halalitude, ni lot
   d'or, ni consigne personnelle de l'assistant, ni discussion, ni identifiant,
   ni clé. Les tests n'utilisent que des données inventées.
   `tests/test_repo_hygiene.py` échoue si git suit un fichier de données.
2. **Pas d'accès programmatique à Trade Republic.** Ni bibliothèque non
   officielle, ni identifiants Trade Republic dans le code ou la configuration.
   Les transactions viennent de l'export CSV officiel, importé à la main.
3. **L'application n'envoie aucun ordre.** Un ordre se prépare et se contrôle
   ici ; il se passe dans l'application Trade Republic, par l'utilisateur.
4. **Le serveur n'écoute que sur 127.0.0.1.** Pas d'exposition sur le réseau,
   pas de service hébergé.
5. **La Halalitude se relève à la main.** L'application ne la calcule pas, ne
   la devine pas et ne cite le nom d'aucun screener dans ce qu'elle publie. Un
   achat s'arrête sur son ticket tant que le statut n'est pas « halal », relevé
   et à jour : c'est le seul contrôle bloquant. Une vente n'est jamais arrêtée.
6. **Les autres règles du portefeuille ne bloquent rien.** Un écart est listé
   et un motif s'écrit à côté. Les types de règles sont dans le code, leurs
   valeurs dans la base de l'utilisateur.
7. **La clé d'API vit dans le gestionnaire d'identifiants du système.** Jamais
   dans le dépôt, dans la base, dans un fichier ou dans la réponse d'un point
   d'accès.
8. **L'assistant ne voit jamais** l'or physique, les paiements par carte ni les
   coordonnées bancaires. Il n'écrit que trois choses, marquées comme venant de
   lui : une note au journal, une proposition de cible, et le brouillon d'un
   ticket quand l'utilisateur le lui demande. Il ne rend aucun ticket « prêt »
   et n'en écrit pas le motif.
9. **Ni conseil, ni urgence, ni levier.** Rien dans l'application ne dit
   d'acheter ou de vendre, ne presse d'agir, n'encourage l'effet de levier. Une
   analyse présente des scénarios, pas une prédiction, et dit ses incertitudes.
10. **Fiches et veilles restent publiques et sourcées.** Elles portent sur une
    liste d'entreprises, sans rien dire de ce qui est détenu. Un fait a une date
    et une source ; l'interprétation est tenue à part et se dit comme telle.

## Comment on travaille

- **Les questions d'abord.** Un choix qui revient à l'utilisateur se pose avant
  d'écrire le code, pas après.
- **Une branche et une demande de fusion par lot.** L'utilisateur relit et
  fusionne lui-même. Personne d'autre ne fusionne ni ne pousse sur `main`, à une
  exception près : les deux tâches planifiées y déposent la fiche du jour et la
  veille de la semaine, et rien d'autre.
- **Chaque demande de fusion dit ce qui est vérifié et ce qui ne l'est pas.**
  La source de cours n'est pas joignable depuis tous les environnements : ce
  qui n'a pas été essayé contre elle est annoncé comme tel.
- **Un gros lot commence par une courte spécification** : ce que ça fait, ce que
  ça ne fait pas, et les critères d'acceptation, validés avant le code. Les
  tickets d'ordre en font partie.
- **Pas de licence** tant que l'utilisateur n'en a pas choisi une.

## Conventions

- Interface, documentation et messages de commit en français simple ; code,
  noms et commentaires en anglais.
- L'argent se calcule en `Decimal` ; les nombres à virgule flottante
  n'apparaissent qu'à la sortie JSON.
- Les migrations SQL sont numérotées et ne se modifient pas une fois fusionnées.
- Un graphique se lit sans la couleur seule : légende, valeurs lisibles, et
  couleurs contrôlées pour les daltoniens.
- Les dépendances restent peu nombreuses ; `scoring.py` et `veille.py`
  n'utilisent que la bibliothèque standard, pour tourner seuls.

## Vérifier avant de proposer

```
uv run ruff format .
uv run ruff check .
uv run pytest -q
cd frontend && npm run build
```

Les quatre passent avant toute demande de fusion. Un changement d'écran se
regarde aussi à l'œil, en clair et en sombre, en large et en étroit.

## Repères

| Dossier | Contenu |
| --- | --- |
| `src/cockpit/` | Calculs, base SQLite, API locale, source de cours, assistant |
| `frontend/src/` | Interface (React, TypeScript, Tailwind) |
| `tests/` | Tests, sur des données inventées |
| `fiches/` | Fiches du jour, barème, liste publique des entreprises |
| `veilles/` | Veilles hebdomadaires et leur format |
| `scripts/` | Lancement sous Windows |
