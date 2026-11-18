# P'tites Ondes — preuve directe OpenAgenda API v2 (18/11/2026)

**Brouillon. Non connecté aux pipelines de collecte ni de publication. Aucune production modifiée.**

## Problème

Le prévalidateur historique exige d'abord une réponse du miroir OpenDataSoft par UID, alors que des événements publics OpenAgenda peuvent en être absents. Une source extérieure peut contenir l'UID exact et les créneaux : elle doit pouvoir être vérifiée **sans exonérer** les autres preuves.

Le 18 novembre, 40 pistes à 4 lieux GPS représentaient seulement 9 UID distincts. Parmi elles, 29 enregistrements Studio 24 sont le **même UID d'exposition familiale** du 5 décembre 2026 au 3 janvier 2027. La page lue n'établissait pas 29 séances horodatées. Aucune fiche quotidienne ne peut être fabriquée sur cette base.

## Contrat OpenAgenda v2 documenté

- Lecture GET /v2/agendas/{agendaUID}/events/{eventUID}, avec clé publique oa_pk_ dans l'en-tête HTTP key (jamais en paramètre URL) : https://developers.openagenda.com/10-lecture/ et https://developers.openagenda.com/authentification/.
- uid immutable ; state=2 pour publié ; status=1 pour programmé ; timings explicites begin/end ; timezone ; location et rights : https://developers.openagenda.com/evenements/structure/ et https://developers.openagenda.com/lieux/structure/.
- Une fiche OpenAgenda peut être participative : une correspondance API ne prouve **jamais** seule l'identité de l'organisateur ou les droits de republication.
- Selon la documentation 2026 de l'API, `rights.license` est un **objet** (`id`, `name`, `url`), non une chaîne. Le concédant `rights.licensor` doit être distingué de l'éditeur `rights.publisher` ; la licence et l'attribution doivent être vérifiées avant publication : https://developers.openagenda.com/licence/.

## Module isolé

Fichier : scripts/ptitesondes_openagenda_v2_direct_evidence.py.

1. Contrôle URL exact sur openagenda.com, identité uid et agenda, sans fausse similitude ni redirection.
2. Associe l'agenda à une paire agenda_slug/agenda_uid + fuseau IANA homologuée indépendamment.
3. Lit l'événement directement sur api.openagenda.com, taille maximale 600 Ko, public-read-key uniquement, aucun token dans les journaux, lecture seule.
4. Refuse non publié, annulé, complet, reporté, retiré, en ligne, sans preuve explicite de famille ou avec identité de titre incorrecte.
5. Compare le lieu et les coordonnées de l'événement à un point **indépendamment documenté**, 65 mètres max ; n'utilise pas de géolocalisation inventée.
6. N'accepte que des créneaux explicites avec offset cohérent avec le territoire, maximum 800 comme la documentation, aucun horaire inventé depuis une plage de dates.
7. Contrôle des codes de territoires français ultramarins GP, MQ, GF, RE et YT : pays non-FR admissible seulement si les champs région et département concordent exactement avec le territoire attendu, plus les exigences de ville, lieu, GPS et fuseau indépendamment homologués.
8. Si un UID regroupe des jours multiples, la décision est « en attente de regroupement ». Aucune conversion en multiples fiches journalières autorisée.
9. Rapport de comptages anonymisés. Drapeaux d'attestation organisateur, droits, âge/accès, dédoublonnage et publication toujours faux.

Le résultat positif ne vaut que **preuve structurelle API v2**. Il n'accorde aucune validation éditoriale, n'écrit aucune fiche publique et ne remplace ni l'organisateur ni le publisher existant.

## Tests, sécurité et limites

Workflow : .github/workflows/ptitesondes-openagenda-v2-direct-proof-tests.yml. Exécute uniquement des tests fictifs adversariaux sur runner public, permissions contents:read, sans secret, sans programmation cron et sans publication.

Tests : dossier fictif de Guadeloupe avec fuseau et codes administratifs vérifiés, refus d'un territoire contradictoire, rapport avec motif de refus arbitraire rejeté, URL falsifiée, UID ou agenda discordant, annulation, report, complet, géographie incohérente, public non familial, droits absents, décalage de fuseau et DST incorrect, occurrence absente, range de dates sans horaires, 25 jours sur un UID conservés en attente de regroupement, clé secrète interdite, HTTP redirigé interdit, rapport anonymisé.

**Aucun test live avec la véritable clé API n'est réalisé dans cette PR.** Il faudra un smoke test de lecture sécurisée sur l'infrastructure existante après validation, sans exposer le secret à la branche PR.

## Suite obligatoire avant tout raccordement de production

1. Registre d'agendas de confiance avec agenda_slug, agenda_uid, timezone, organisation institutionnelle réellement vérifiée et licence examinée, sans exception par concert/sortie.
2. Contrôle live de la réponse OpenAgenda v2 sur un jeu d'UID absents d'ODS, y compris un événement multi-jours ; zéro écriture.
3. Vérification organisateur indépendante, des conditions de visite, de l'âge annoncé et des coordonnées de lieu, y compris ultramarines ; anti-doublons par UID et identification des séries versus expositions continues.
4. Prévisualisation privée et jeux de tests sur l'historique avant intégration du fallback ODS dans la chaîne de publication.
5. Autorisation explicite avant toute fusion, déploiement ou ouverture des nouvelles catégories à la carte.

Non modifiés : scripts/ptitesondes_candidate_promotion.py, scripts/merge_policy.py, catalogues, crons, runners privés, Infomaniak et Grosses Ondes.

## Lot de raccordement en lecture seule (18 novembre, après le premier audit)

Le correctif du contrat `rights` exige désormais la **forme réellement documentée par API v2** : `rights.license.id` et `rights.licensor.name`, pas une licence sous forme de texte. La licence identifiée reste **non examinée** au sens éditorial : le champ `rights_reviewed` demeure faux. Selon https://developers.openagenda.com/licence/, l'identité du concédant peut différer de celle de l'éditeur de l'agenda, et une mention de source/licence/date de mise à jour sera nécessaire en cas de réutilisation réelle.

Le nouveau module sans I/O `scripts/ptitesondes_openagenda_v2_preintegration.py` prépare trois contrats **sans admission ni publication** :

1. **Agenda** : UID, slug, fuseau IANA et origine institutionnelle épinglés dans un registre *maintenu* par une personne, puis comparaison exacte avec les métadonnées API. Le drapeau OpenAgenda `official` ou un nom d'institution saisi librement ne remplace pas la preuve indépendante. Une page institutionnelle récupérée séparément doit contenir un véritable lien HTML HTTPS vers la racine exacte de l'agenda ; les ressemblances de slug et les domaines usurpés échouent. Même la concordance ne vaut pas attestation que **chaque événement** de l'agenda a été créé par l'organisateur. La fonction ne s'occupe pas des permissions de publication.
2. **Regroupement** : contrôle des créneaux datés et horodatés, 24 h max, absence de chevauchement, fuseau local, UID immuable. Un UID multi-jours reste **bloqué** sans source organisatrice indépendante. Une exposition dont la période est explicitement documentée devient une proposition de **fiche de période** à examiner ; une série n'est reconnue qu'en cas de correspondance intégrale des horaires officiels. Dans les deux cas, `daily_cards_authorized=false` et `publication_authorized=false`. Les 29 journées possibles du Studio 24 ne deviennent jamais 29 cartes par cette seule qualification.
3. **Fallback ODS** : la voie directe ne peut être envisagée qu'en cas d'UID prouvé absent du miroir sur une requête ODS terminée et interprétable ; panne, timeout ou réponse ambiguë restent bloquants, après preuve structurelle API, identité de l'agenda, lien institutionnel indépendant et absence d'UID historique connu. Les incohérences ou divergences d'ODS sont **bloquantes**, pas contournables. Les cas multi-jours sont retenus pour regroupement. La seule issue favorable est `direct_source_candidate_for_remaining_gates` : contrôle de l'organisateur exact, droits et crédits, âge, accès, catégories, GPS, dédoublonnage et synchronisation historique restent obligatoires.

### Connexion réelle encore interdite

Le promoteur `scripts/ptitesondes_candidate_promotion.py`, `merge_policy.py`, `proof_text.py`, la collecte privée, les catalogues, les crons et le site **ne sont pas modifiés**. La lecture API n'a pas été testée live sur la branche PR, faute de clé publique de lecture utilisable dans cet environnement isolé ; ne jamais injecter une clé dans le code, un rapport public ou un déclenchement PR non fiable. Un `workflow_dispatch` de lecture seule avec l'environnement de secrets sécurisé et un jeu d'UID explicitement validés devra être préparé puis exécuté **hors PR**, après revue des identités des agendas.

La configuration privée `Sarogal/PtitesOndes/automation/sources.json` référence actuellement 16 UID d'agendas ; cela constitue un **inventaire de découverte**, pas 16 attestations officielles. Les métadonnées propriétaires, les domaines institutionnels, l'identité du concédant et les licences doivent être recensés et vérifiés agenda par agenda, sans recopier le registre privé dans les artefacts publics. L'API exige une clé `oa_pk_` en en-tête `key`, jamais en URL.

### Couverture des tests

Suites hors réseau : `test_ptitesondes_openagenda_v2_direct_evidence.py` et `test_ptitesondes_openagenda_v2_preintegration.py`. Les scénarios couvrent les structures réelles de licences v2, identifiants modifiés, fausses URL d'institution, ancre HTML absente, agenda non concordant, exposition de 29 jours, séries aux horaires incomplets, décalages horaires et chevauchements, anciennes fiches, ODS contradictoire, et les faux drapeaux d'approbation. Aucun test ne publie de fiche ni ne franchit une vérification éditoriale.
