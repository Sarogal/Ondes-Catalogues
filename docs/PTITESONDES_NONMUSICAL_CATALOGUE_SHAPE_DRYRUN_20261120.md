# P’tites Ondes — Contrat de schéma non musical en simulation (20 novembre 2026)

**Développement isolé, sans publication ni modification de production.**

## État et raison du lot

Les PR #473 et #477 prouvent déjà une partie de l'existence des sorties familiales HTML, de leurs séances exactes et des risques de provenance. Mais le publisher historique `ptitesondes_candidate_promotion.py` et le validateur `merge_policy.py` sont prévus pour des catégories musicales déjà présentes dans le catalogue.

L'objectif de ce lot est de **simuler la compatibilité de l'ensemble des 14 catégories de `FAMILY_TYPES`** avec le schéma actuel, sans ouvrir le publisher historique, ni prétendre disposer de signatures indépendantes de source, droit, lieu ou organisateur.

## Ce que réalise la fonction

`scripts/ptitesondes_nonmusical_catalogue_shape_dryrun.py::simulate_nonmusical_catalogue_shape()` :

1. Reçoit une liste bornée de dossiers mémoire et une **copie explicite du catalogue de référence** accompagnée de son empreinte SHA-256 de cohérence.
2. Exige que le catalogue historique fourni aux vérifications de chaque événement soit exactement identique au catalogue de la simulation, pour éviter les duplications invisibles.
3. Rejoue la vérification de la séance HTML sur une source institutionnelle précédemment épinglée, du public familial et des conditions de participation ; les droits de réutilisation peuvent être encore en attente, mais **jamais autoriser la publication**.
4. Construit seulement *en mémoire* une représentation **hypothétique** avec une catégorie parmi les 14 codes autorisés, un libellé de catégorie connu, un horaire strict, un lieu provenant d'un registre externe au collecteur et un département/région/libellé de source provenant d'un autre pin.
5. Vérifie le schéma `merge_policy.valid()` avec un jeu de catégories hypothétiquement étendu, sans changer ses contrôles en production. Les dates factices utilisées pour vérifier le schéma ne constituent pas une attestation de nouvelle vérification.
6. Refuse les doublons exacts et conserve en attente les séries ambiguës, y compris lorsqu'un agrégateur tiers a déjà publié le même titre/lieu/date. Deux séances de la même fiche officielle, chacune avec un horaire explicitement corroboré, sont conservées séparément *dans la simulation*.
7. Produit **seulement des compteurs fixes** ; ni fiches, ni ajouts, ni patch.v1, ni URLs, ni coordonnées, ni contenu des candidats ne sont exposés. Aucune écriture, aucun token, aucune connexion au publisher.

Les événements au prix inconnu sont projetés avec **« Voir conditions »** : jamais « Gratuit » si aucune source ne l'affirme. Une tranche d'âge absente ne reçoit aucun âge numérique inventé.

## Ce que cela ne démontre pas

- Le registre MPT conserve `pending_source_legal_review` : les sorties ne sont pas autorisées à réutilisation ni publication.
- Les coordonnées de la projection viennent d'un registre précédemment revu, **pas d'une nouvelle vérification IGN/BAN** de chaque lieu.
- Le département, la région et le libellé de la source sont des **données de simulation** : aucune admission ne peut utiliser un pin administratif fourni par un candidat comme preuve.
- L'empreinte d'un catalogue reçu par l'appelant vérifie son intégrité *interne*, mais ne démontre pas qu'il s'agit de la dernière version réellement publiée. Un publisher devra refetcher indépendamment le catalogue live et comparer les empreintes à l'instant de publication.
- Il manque le raccordement aux dossiers privés, une preuve d'organisateur courante, la politique source/base, la révocation des droits et l'admission séparée. Le vérificateur HTML historique exige encore certains champs absents des nouveaux événements.
- Le modèle de collision conservateur peut retenir des représentations distinctes d'une série : l'étape indépendante doit vérifier leur véritable horaire plutôt que les fusionner ou les écarter.

**Tous les compteurs de compatibilité sont hypothétiques** ; `publication_ready=false`, `approval_granted=false`, `publisher_connected=false` et `public_writes=0` dans chaque réponse.

## Relecture et suite

Tests synthétiques avec le catalogue public du dépôt, 549 fiches au contrôle précédent : catégories non musicales, lieux distincts, sessions multiples, duplications inter-sources, empreintes obsolètes, absence de date, âge et tarif, valeurs adversariales, catalogue immuable. CI HTML et synchroniseur complet à vérifier.

Ensuite seulement, développer le **vérificateur d'admission indépendant** des champs du candidat, avec refetch HTTPS et preuve GPS/droits/organisateur revérifiés, plus une politique de publication non musicale append-only séparée du moteur musical. Ne pas fusionner sans revue explicite.

**Aucune modification de GitHub Pages, Infomaniak, dépôt privé, catalogue ou publisher.**
