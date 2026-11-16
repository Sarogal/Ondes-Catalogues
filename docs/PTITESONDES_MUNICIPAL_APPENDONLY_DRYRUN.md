# P’tites Ondes — simulation append-only municipale sur les 548 sorties

**16 novembre 2026 — expérimentation hors production uniquement.**

## Périmètre vérifié

PR publique brouillon #330, empilée sur #328 (vérification humaine), elle-même empilée sur #325 (prévalidateur du Gosier), #323 (contrat de catégories non musicales).

- Fichier : `scripts/ptitesondes_municipal_appendonly_dryrun.py`.
- Tests : `tests/test_ptitesondes_municipal_appendonly_dryrun.py`.
- CI publique sans secret : `.github/workflows/ptitesondes-municipal-appendonly-tests.yml`.
- Catalogue réellement lu pendant les tests : `docs/ptitesondes/sorties.json`, version 3, **548 événements historiques** au 16/11/2026, `updated_at=2026-11-16T19:48:51+01:00`.
- La première CI est verte : https://github.com/Sarogal/Ondes-Catalogues/actions/runs/43959188193 — **11 tests réussis**.

## Ce que signifie « simulation »

Le programme ne produit aucun fichier public, aucun patch et n'édite aucun catalogue. Il crée une copie **en mémoire uniquement** de l'original, examine les candidats du dossier municipal avec le prévalidateur indépendant, puis simule des ajouts à la fin de cette copie. Il vérifie, avant de retourner seulement des compteurs, que les 548 fiches originales, leurs contenus, leur ordre et `updated_at` sont intacts.

Exemples des tests : 548 → 549 **hypothétiquement** avec une occurrence ; 548 → 550 avec deux dates distinctes d'une même série. **Zéro** suppression, correction, écriture publique et droit de publication.

Pour chaque séance : preuve officielle page + agenda de la mairie, date et horaires exacts, identité du lieu, GPS reconnu par le contrat #323, catégories jeunesse explicitement admises dans la simulation, âge, absence de contradiction dans les conditions, période d'événement, doublons d'identifiant et doublons sémantiques avec plages de dates.

La date de vérification officielle **et** celle de vérification géographique doivent être fournies par les dossiers vérifiés. Elles ne sont pas inventées par le script et toute preuve dépassée échoue. La signature du dossier et l'approbation restent soumises à #328, non présentes ici.

### Bloqueur avéré du vrai synchroniseur

Le fichier actuel `scripts/merge_policy.py` dérive les catégories admises des **sept catégories historiques** présentes dans le catalogue. Il rejette donc `lecture-jeunesse`, `atelier-numerique`, `lecture-cinema`, `jeux-famille`. De même, `proof_text.verify_event` a été conçu pour le circuit des fiches OpenAgenda ou de ses organisateurs autorisés.

**Il serait incorrect de qualifier un candidat du Gosier de « publiable » après ce test.** La simulation construit un jeu de catégories élargi **local et hypothétique**, sans modifier `merge_policy`, sans fabriquer de référence historique et sans contourner le vérificateur de production. Le module renvoie systématiquement `publication_ready=0`, `approval_granted_to_publisher=false`, `public_writes=0`.

La preuve du contrôle municipal et les tests existants OpenAgenda restent indépendants. Une future voie d'admission municipale devra faire l'objet d'une PR séparée et validée pour le réel synchroniseur, sans affaiblir ses contrôles.

## Conditions avant toute première sortie ultramarine

1. Vérifier l'approbation humaine **réelle** du dossier privé, chaque occurrence individuellement (aucune à ce jour).
2. Déployer la v173 cartographique seulement après une nouvelle comparaison à la v172 réellement servie et contrôle navigateur de la carte + lieux permanents.
3. Mettre en œuvre une **nouvelle voie municipale stricte**, avec schéma public autorisant explicitement les catégories jeunesse et une preuve officielle indépendante par séance, au lieu de tromper la voie OpenAgenda.
4. Relire tarif et inscription non précisés et n'afficher que « Voir conditions », jamais « Gratuit » déduit du silence.
5. Tester une vraie proposition sur le catalogue public courant au moment de l'opération, confirmer zéro modification historique, puis demander validation de la publication.
6. Ne pas réactiver d'actions programmées sur les runners privés.

Ce document est un compte rendu de répétition technique, **pas une autorisation**.
