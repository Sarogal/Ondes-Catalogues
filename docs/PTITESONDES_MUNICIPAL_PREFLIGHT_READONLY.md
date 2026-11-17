# P’tites Ondes — Prévalidation municipale indépendante, phase isolée

**16 novembre 2026 — DRAFT, aucune publication, aucun déploiement.**

## Dépendance et portée

Cette branche est volontairement dérivée de la branche de la PR publique #323
(\`feat/ptitesondes-nonmusic-release-contract-20261116\`) et vise une PR
empilée. **Ne pas la fusionner avant la PR #323 et un accord explicite.**

Le module \`scripts/ptitesondes_municipal_preflight.py\` reprend les règles
déjà posées par la PR #323 sans les remplacer. Il ajoute une **contre-vérification
indépendante des deux pages officielles de chaque séance** :

1. Vérification des rapports privés de revue et d'accès, identité exacte du
   lieu, catégorie jeunesse, âge, date et déduplication par le contrat #323.
2. Vérification de l'URL municipale HTTPS autorisée uniquement ; réponse
   HTML bornée et sans redirection.
3. Lecture isolée de la fiche officielle, de son titre, de l'âge explicitement
   indiqué, du lieu, du jour et des deux horaires.
4. Lecture isolée de la **carte SPIP de la même occurrence** dans le calendrier
   municipal : identifiant titre et lieu identiques, même titre/lieu, même
   jour/mois/année, même début/fin. Une autre carte ne peut pas fournir l'heure.
5. Recherche des annulations ou reports et contre-vérification de ce qui
   est *effectivement* écrit pour le tarif et l'inscription.
6. Si le prix ou l'inscription ne sont pas indiqués, retour
   \`editorial_conditions_required\` : jamais « Gratuit » ni
   « Sans inscription » par inférence.
7. Résultat de diagnostic **strictement privé** : aucune approbation, aucun
   \`patch.v1\`, aucune insertion ou mutation du catalogue.

## API

\`audit_municipal(review, access, catalogue, today, get=read_official)\`.

La fonction \`get\` peut être remplacée dans les tests par une source HTML
déterministe, sans accès réseau. Les rapports complets restent privés. Sur
les runners publics, seuls des compteurs agrégés peuvent être imprimés.

Le script peut être invoqué avec \`--review\`, \`--access\`,
\`--catalogue\`, \`--date\` et \`--output\`. Le fichier de sortie doit être
inexistant et doit être enregistré uniquement dans l'espace privé approprié.

## Limites explicites — blocages avant tout lancement public

- **Aucune intégration aux workflows de production.** Aucun nouveau cron.
- **Aucune approbation privée vérifiable n'a été ajoutée.** Le mécanisme
  d'approbation doit être distinct des fichiers fournis par les collecteurs,
  authentifier l'acteur et l'état de la preuve, et être contre-vérifié.
- **Aucun éditeur de patch municipal n'est activé.** Le synchroniseur et
  \`proof_text.verify_event\` restent conçus pour OpenAgenda. Une voie
  municipale séparée et approuvée reste à développer.
- La taxonomie des quatre nouvelles catégories et son rendu
  \`sorties-v172.js\` doivent être prévalidés sur copie, puis déployés avec
  autorisation explicite avant publication de ces catégories.
- Le registre géographique proposé en PR #305 n'est pas encore fusionné.
- Ce module n'a pas le droit de modifier l'historique, de revendiquer
  \`approval_granted\` ni de déduire la gratuité à partir d'une page muette.
- Les essais unitaires utilisent des HTML synthétiques. Une exécution réelle,
  en mode lecture seule, des **neuf occurrences privées** reste indispensable
  avant de conclure que toutes passent les deux contre-vérifications.

## Évolution nationale

Le schéma est d'abord restreint à la ville du Gosier (source autorisée
explicitement) pour éviter une admission aveugle d'URLs non vérifiées.
Un registre futur de municipalités devra documenter séparément les hôtes,
parsers, preuves de bâtiments et exigences d'âge de chaque source.
Les traitements OpenAgenda métropolitains, corses et CINOR restent inchangés.
