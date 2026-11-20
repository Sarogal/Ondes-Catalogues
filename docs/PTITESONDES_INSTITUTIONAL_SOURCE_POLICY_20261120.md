# P’tites Ondes — Politique de confiance et de réutilisation par source

**20 novembre 2026 · développement isolé · aucune fusion ni publication.**

## Objectif
Supprimer l'adaptation à **chaque événement** : une source institutionnelle approuvée peut fournir des dizaines de sorties, dont les dates, lieux, publics, accès et doublons devront être revalidés **individuellement**. La provenance et les conditions de réutilisation sont définies **par source**, vérifiables, expirables et révocables.

## Nouveaux éléments
- **config/ptitesondes_institutional_source_policies.json** : registre maintenu séparément du collecteur, une entrée par hôte ; aucun statut de droit hérité de la fiche d'événement.
- **scripts/ptitesondes_institutional_source_policy.py** : vérification stricte d'identité de domaine/index/préfixe HTTPS, page de l'éditeur et source officielle externe, politiques de réutilisation datées (maximum 180 jours). L'entrée de production ne lit que ce registre commité ; le collecteur n'a pas de champ de substitution.
- **scripts/ptitesondes_institutional_source_live_check.py** : vérifie un lien visible depuis une page d'autorité indépendante et l'accessibilité des mentions légales, avec transport HTTPS sans redirection, lecture bornée et rapport anonyme.
- **scripts/ptitesondes_nonmusical_html_gate_router.py** : après la preuve de séance, public familial, accès, catalogue historique et lieu, retourne un état source précis. Une éventuelle revue de source n'octroie jamais des droits à une fiche.

## Exemple vérifié : Maisons pour Tous Montpellier

Sources consultées le 20 novembre 2026 :
- Mentions légales MPT : https://mpt.montpellier.fr/index.php/mentions-legales — éditeur déclaré : Ville et Métropole de Montpellier.
- Page indépendante de la Ville : https://www.montpellier.fr/campagnes/rencontres-artistiques-doctobre-decembre-2026 — renvoie vers les établissements du portail MPT.

Les références documentent **la provenance du site**, pas l'autorisation de copie ou d'extraction massive, la titularité des photos, la validité d'une licence d'événement ou les droits sur une base de données.

La politique MPT est enregistrée comme **pending_source_legal_review**. Aucun événement n'est publiable via ce statut.

## Règles de sécurité
- Source non enregistrée : revue de la source requise.
- Registre invalide, domaine ressemblant ou préfixe différent : refus.
- Source non revue juridiquement : revue des faits et de la base à effectuer.
- Reproduction restreinte : aucune admission.
- Revue expirée/future ou contradictoire : renouvellement requis.
- Revue factuelle documentée et datée : **reste conditionnée** à une preuve courante de la séance, à l'organisateur, au GPS du lieu, aux droits tiers, à l'anti-doublon du catalogue live et au schéma non musical du publisher.

Une mention légale ou une déclaration OpenAgenda ne suffit jamais à faire passer rights_reviewed, publication_ready ou approval_granted à true.

## Tests et limite
Tests adversariaux hors réseau, lecture de référence institutionnelle en réseau sur les PR, compteurs publics sans identifiants. La vérification distante qui échoue produit un état non confirmé, pas une fausse attestation.

Le module ne modifie pas le synchroniseur de production, l'application, Infomaniak, le dépôt privé, les catalogues, le publisher musical ou GitHub Pages. Les futures politiques de source pourront être soumises à revue GitHub sans changement de code par événement.

## Suite
Construire un contrat de publication **non musicale** en dry-run qui accepte les catégories prévues dans FAMILY_TYPES, distingue les informations non précisées de contradictions, préserve le catalogue historique et rejette les doublons inter-sources. Intégration uniquement après vérification de la provenance et des droits au niveau source et événement.

**Ce lot reste un diagnostic sans écriture.**
