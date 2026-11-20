# P'tites Ondes — Adaptateur national Schema.org Event (source-only)
**Date : 20 novembre 2026. PR isolée, empilée sur #495. Aucune publication.**

## Besoin
Le parcours HTML actuel confirme les séances des Maisons pour Tous Montpellier, mais n'est pas réutilisable tel quel pour les innombrables sites municipaux et institutionnels français. Un format structuré commun, Schema.org Event en JSON-LD, permet d'extraire des pistes sur des sites distincts sans créer un parseur par événement ni une liste exhaustive de communes.

## Développement
- Nouveau parseur pur : `scripts/ptitesondes_generic_schemaorg_event_discovery.py`.
- Lit un enfant HTML préalablement choisi par un index officiel épinglé indépendamment. Refuse un domaine, chemin ou fuseau non conforme à la configuration externe approuvée.
- Reconnaît les objets `Event` et leurs sous-types dans des blocs Schema.org JSON-LD, y compris via `@graph` et `subEvent`.
- Pour une occurrence exacte, exige le jour, l'heure et le lieu avec une commune explicitement citée. Plusieurs séances dans la même journée restent distinctes ; aucune série récurrente ni période de plusieurs jours n'est étendue en dates imaginaires.
- Fuseaux IANA explicitement configurés couvrant métropole, Corse, DROM, Saint-Pierre-et-Miquelon, Saint-Barthélemy, Saint-Martin, Polynésie française, Nouvelle-Calédonie, Wallis-et-Futuna. Les heures locales ambiguës durant les transitions DST restent en attente.
- Aucune liste préapprouvée de lieux : événements sur une place, dans une rue ou un espace temporaire restent des pistes si le lieu et la commune sont déclarés.
- Titres non classés conservés comme pistes privées, plutôt qu'être éliminés. Les 14 catégories non musicales existantes restent l'option de classification ; les thématiques explicitement musicales ne sont pas réétiquetées.

## Garde-fous
- Une description JSON-LD, même sur un site officiel, est une **déclaration de source**, pas une preuve indépendante ni une attestation de sa visibilité sur la page.
- L'adaptateur ne reconnaît **ni** l'organisateur réel, ni le droit à la réutilisation, ni une licence, ni des coordonnées GPS, ni une date confirmée par une preuve visuelle indépendante.
- Les tarifs et inscriptions non confirmés restent 'non précisés', même en présence de `offers.price=0` dans les métadonnées.
- Aucun fetch réseau, API, fichier, patch, Git push, catalogue public, publisher ou Infomaniak.
- Le code n'est pas encore branché sur la découverte nationale : le chantier suivant doit créer un sélecteur d'adaptateurs depuis un registre institutionnel indépendant, puis repasser les preuves de séance/organisateur/GPS/droits avant toute admission.

## Validation
Tests unitaires synthétiques : séances multiples, lieux et villes inhabituels, fuseaux ultramarins, horodatages et DST, annulations, séries sans horaire, sécurité des domaines, XSS et rapports anonymes. La PR reste en brouillon jusqu'à tous les tests réussis.
