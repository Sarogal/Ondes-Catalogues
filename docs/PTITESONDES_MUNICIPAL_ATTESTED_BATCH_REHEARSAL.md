# P'tites Ondes — lot municipal attesté, simulation tout ou rien

**17 novembre 2026 — DRAFT, contrôle hors ligne et lecture seule.**

## Chaîne

PR empilée sur **#337 → #335 → #334 → #332 → #330 → #328 → #325 → #323**.
Dépendances séparées **#305** (registre GPS homologué), **#327** (prévisualisation v173),
**#310/#322** (collecte ultramarine) et PR privées **#64/#65/#66**.
Aucune fusion et aucune insertion dans `docs/ptitesondes/sorties.json`.

Le point de référence a été revérifié le 17 novembre :
`https://sarogal.github.io/Ondes-Catalogues/ptitesondes/sorties.json`
correspond **octet pour octet** au fichier GitHub (version 3, 548 fiches,
`updated_at = 2026-11-16T19:48:51+01:00`). Ces valeurs ne doivent jamais
être présumées valables lors d'une future tentative de publication.

## Fonctionnement et conditions de refus

`scripts/ptitesondes_municipal_attested_batch_rehearsal.py` propose
`inspect_attested_municipal_sync(reference, current, bundles, today, *,
reference_sha256, current_sha256, token, source_get, github_get,
geo_check, registry, now)`.

Chaque élément de `bundles` doit contenir **exactement** :
`review`, `access`, `manifest`, `receipt`.
Une attestation de lot ne remplace jamais les attestations individuelles.

1. Vérifier les deux SHA du catalogue et l'identité exacte de l'historique
   (aucune suppression, modification, ni réorganisation de la partie ancienne).
2. Rejouer **#334** pour toutes les occurrences : source officielle,
   calendrier, accès, décision humaine privée #332, anti-doublons internes
   et entre sources, contrôle GPS de base, empreinte du catalogue courant.
3. Si le lot est intégralement accepté, rejouer **#337 pour chacune** :
   reçu individuel lié au manifeste et SHA courant de la PR privée,
   événement, calendrier, conditions, catalogue, entrée GPS,
   provenance institutionnelle et géographique sur des hôtes distincts.
   L'attestation GitHub du propriétaire doit être valide, non révoquée,
   et émise depuis 14 jours au maximum selon l'heure du **serveur GitHub**.
4. Si TOUTES les attestations sont vérifiées, appeler **#335** pour une
   simulation exclusivement en mémoire. Une seule séance refusée entraîne
   **zéro ajout hypothétique** pour tout le lot.

Les dates de planification nécessaires au modèle #335 sont produites
localement pour le **calcul fictif seulement**. Elles ne sont ni lues dans
les dossiers des collecteurs ni utilisées pour prétendre à une vérification
officielle ou GPS. La version actuelle de #337 **ne recontacte pas le
fournisseur géographique** : une vérification indépendante restera
impérative avant toute publication.

La réponse ne contient que des booléens, compteurs, empreintes et motifs
agrégés. Aucun événement, identifiant individuel, `patch.v1`, `additions`,
catalogue modifié ou jeton ne sort de l'orchestrateur.

Valeurs **inconditionnelles** :
`publication_ready=false`,
`approval_granted_to_publisher=false`,
`public_writes=0`. Aucun branchement vers le publieur.

## CI publique

`python -m unittest discover -s tests -p 'test_ptitesondes_municipal_attested_batch_rehearsal.py' -v`

Le workflow `ptitesondes-municipal-attested-batch-rehearsal-tests.yml`
est activé **uniquement** sur push de sa branche ou pull_request ciblée.
`contents: read`, aucun secret, aucun cron, aucun runner privé.
La suite complète `sync-tests.yml` s'exécute séparément pour la PR.

Les neuf occurrences de test du Gosier sont **synthétiques**, y compris
les IDs 9001–9009, les preuves et décisions privées simulées, les
horaires/conditions de tests et le registre GPS injecté. Leurs succès
ne signifient pas que les événements réels ont été admis.

## Dépendances éditoriales et publication réelle

- Les **neuf séances annoncées au Gosier** restent à contrôler sur les
  sources réelles avec dates, accès et lieu, sans inventer la gratuité ni
  les modalités d'inscription. Une décision `SOURCE_ONLY` explicite,
  authentifiée et révocable est requise pour afficher « Voir conditions »
  quand l'accès est inconnu.
- La séance CINOR du 18 novembre relève du **circuit OpenAgenda distinct**.
- La branche #305 doit être examinée et ses coordonnées recontrôlées
  auprès du fournisseur externe ; la prévisualisation v173 #327 doit
  être approuvée séparément avant toute nouvelle catégorie visible.
- La France métropolitaine et la Corse et leurs catégories musicales
  historiques restent inchangées.
- Aucun code du publisher, aucun workflow récurrent, aucune configuration
  Infomaniak, aucun fichier Grosses Ondes ne sont modifiés.
- Une publication future demandera un **autre contrôleur terminal**,
  des dossiers privés réels actualisés et une **autorisation explicite
  de fusion et de déploiement**.

## Retour arrière

Cette PR peut être laissée en brouillon ou abandonnée sans toucher
aux catalogues et au site : aucun chemin d'écriture de production.
