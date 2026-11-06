# Grosses Ondes — migration progressive vers les runners publics

## Objectif et limites

Les runners GitHub Actions **standard** du dépôt public `Sarogal/Ondes-Catalogues` n'épuisent pas le quota de calcul du dépôt privé. Le dépôt public héberge déjà les mécanismes de synchronisation protégée des festivals et concerts et une découverte ministérielle.

Le pilote `grossesondes-regional-public-discovery.yml` permet une **exécution manuelle de diagnostic** sur quatre des **18 index institutionnels publiquement répertoriés**, couvrant 13 régions dans sa configuration. Ses deux anciennes planifications quotidiennes ont été retirées, car le moteur complet `grossesondes-festivals-private-intake-on-public-runners.yml` exécute désormais la collecte à **06:24 et 18:42 UTC** avec état privé protégé. Il n'est pas utile de relancer simultanément le pilote. Il produit uniquement des compteurs de liens visibles et de disponibilité. Il **ne** crée **aucune** fiche, ne valide **aucune** date, n'ouvre **aucune** URL découverte, et n'écrit dans **aucun** catalogue public. Les rapports GitHub Actions dans un dépôt public sont eux-mêmes publics : n'y inclure aucun jeton, aucune donnée confidentielle ni dossier interne.

## État de bascule au 6 novembre 2026

Les veilles planifiées Festivals et Concerts ont été transférées sur les runners publics. Leurs secrets restent dans les paramètres Actions et les propositions/états sont conservés dans les branches privées. Les anciens crons privés correspondants ont été supprimés (PR privée #299, PR publique #175). Les premières exécutions **automatiques** de cette nouvelle architecture doivent toujours être inspectées avant de considérer la régularité comme prouvée.

Le moteur de diagnostic régional ancien reste disponible en manuel, mais ses crons ont été retirés pour éviter deux séries de requêtes identiques vers des sources régionales.

## Où conserver les secrets ?

- **Jamais** dans les fichiers versionnés, les variables `vars`, les journaux ni les artefacts.
- Les clés nécessaires à une veille publique peuvent être placées en **GitHub Actions Secrets** du dépôt public, éventuellement dans un environnement protégé. La valeur n'est pas affichée aux visiteurs, mais elle est accessible au code exécuté par un job autorisé : ne pas exécuter de contributions non fiables avec des secrets.
- Un secret d'un dépôt privé n'est **pas automatiquement disponible** dans un autre dépôt public. Les clés nécessaires doivent être configurées séparément, **sans être partagées dans un chat**. Pour le futur moteur Concerts, la clé `TICKETMASTER_API_KEY` devra être installée comme secret Actions dans le dépôt public seulement après audit du code et de l'usage.
- `GROSSES_ONDES_INTAKE_READ_TOKEN` est déjà référencé par la synchronisation publique. Il doit rester limité à `Sarogal/GrossesOndes`, permission **Contents: Read-only**. Ne jamais remplacer cet accès de lecture par un jeton d'écriture généraliste.
- Les scripts de collecte publics doivent utiliser le `GITHUB_TOKEN` uniquement avec `contents: read`. La publication est réservée à des workflows séparés, avec approbations et contrôles indépendants.

## Ordre de migration

1. **Pilote régional sans clé** : vérifier les 18 index publics, la rotation, les blocages, le coût gratuit, les tests sur le dépôt public. Ne rien publier. **Ce pilote n'est pas encore le moteur complet.**
2. **Moteur Festivals complet** : auditer les modules et données privées, n'exposer que les sources et règles non confidentielles ; déplacer progressivement collecte, indexation, pagination, qualification et tests vers le public. Concevoir un stockage d'état qui n'expose pas les dossiers éditoriaux internes.
3. **Concerts** : traiter séparément les adaptateurs sans clé et l'accès Ticketmaster. Limiter la portée des éventuels secrets ; tests de pull request **sans secret**, collecte seulement depuis `main`.
4. **Sorties et lieux P'tites Ondes** : conserver les workflows publics existants, mutualiser les contrôles, éviter les doublons de crons.
5. **Bascule** : vérifier la parité des résultats et les protections de publication, puis seulement désactiver les crons équivalents dans le dépôt privé. Ne pas transformer le dépôt de l'application Android en dépôt public.

## Garanties essentielles

- Pas de déclencheur `pull_request_target` exécutant du code non approuvé avec des secrets.
- Aucun jeton d'écriture vers `GrossesOndes` dans les jobs de découverte du dépôt public.
- Secrets de publication dans les jobs protégés uniquement ; permissions minimales.
- Pas de copie brute des dossiers d'approbation ou des données privées dans le dépôt public.
- Aucune promotion d'une piste « thématique » en festival confirmé sur la seule foi d'un titre, d'un calendrier ou d'une date inférée.
- Ne pas désactiver les veilles privées tant que le remplacement public n'est pas validé et persistant.
