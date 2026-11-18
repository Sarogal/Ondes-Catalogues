# P'tites Ondes — préparation du recensement OpenAgenda v2 authentifié

**18 novembre 2026 — PR DRAFT, NON FUSIONNÉE, AUCUNE LECTURE AVEC LA CLÉ ENCORE EXÉCUTÉE.**

## Finalité

La PR #371 a livré les lecteurs API v2 et le compteur anonymisé des agendas. Elle a été fusionnée séparément le 18 novembre, mais aucun test réel authentifié sur les 16 UID configurés n'a été observé. Les tests du lecteur existant sont hors réseau et utilisent des données synthétiques.

Cette PR propose seulement un workflow **manuel de branche principale** qui réutilise le code existant en lecture seule. Aucun nouveau cron ni consommation régulière de runner privé.

## Chaîne de confiance

1. Déclencheur unique : workflow_dispatch. Le job ne s'exécute que si github.repository vaut Sarogal/Ondes-Catalogues et github.ref vaut refs/heads/main ; aucune exécution sur PR n'est acceptée.
2. Checkout du code public par le commit immutable github.sha, permissions contents:read, persist-credentials:false.
3. Checkout temporaire et parcimonieux de Sarogal/PtitesOndes, branche main, **uniquement** automation/sources.json avec le secret PRIVATE_INTAKE_READ_TOKEN déjà utilisé par l'infrastructure existante ; aucun secret d'écriture.
4. Le script connu scripts/ptitesondes_openagenda_v2_agenda_census.py utilise OPENAGENDA_READ_KEY comme **clé publique de lecture** (préfixe oa_pk_) en en-tête HTTPS, sans redirect ni paramètre URL contenant la clé.
5. Sortie console : uniquement compteurs anonymisés des identités API exactes, drapeaux official auto-déclarés, liens institutionnels à examiner, agendas indisponibles. Aucun titre, UID, slug ou URL de candidat privé.
6. Suppression du checkout privé à la fin du job. Aucun artifact, commit, patch, approbation ni déploiement.

Les tests adversariaux du script d'inventaire livré par #371 restent applicables. La suite tests/test_ptitesondes_oa2_trusted_census_workflow.py inspecte le workflow pour garantir la séparation du déclencheur manuel, de main et des secrets.

## Limites

- Une identité d'agenda présente dans l'API ne prouve **pas** que son propriétaire est institutionnel. Le drapeau official et l'URL auto-déclarée ne suffisent pas ; les sites institutionnels doivent être recoupés indépendamment.
- Aucun événement du backlog n'est vérifié par ce recensement : il ne remplace pas le smoke test sur UID absents d'ODS, les séances, les licences ni le contrôle du lieu/GPS.
- Le workflow ne fonctionnera que lorsque cette PR aura été relue puis **explicitement autorisée à la fusion**. Ne jamais exposer les secrets au code non fusionné d'une PR ou exécuter une branche non fiable.
- Si le token privé ou la clé publique de lecture manque, le job échouera et ne doit pas être présenté comme un succès d'API authentifié.

## Suite

Après revue et autorisation explicite, lancer manuellement le recensement sur main ; conserver uniquement le rapport anonymisé. Ensuite préparer un échantillonnage temporaire sécurisé des UID réellement présents dans le backlog (ODS absent/pré­sent, multi-jours, non musical, ultramarin, publié), puis l'audit indépendant de l'organisateur et les conditions de réutilisation. Aucun déploiement site Infomaniak n'est requis pour le recensement.
