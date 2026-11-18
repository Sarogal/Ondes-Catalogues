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

## Lecture de sources publiques réelles, sans clé OpenAgenda (18/11/2026)

Un contrôle externe du miroir public OpenDataSoft a interrogé l'UID exact `27039422` (`select=uid`, `where=uid='27039422'`, `limit=2`) : **`total_count=0`, `results=[]`**. La page OpenAgenda d'origine [Villeurbanne - Agenda culturel](https://openagenda.com/fr/villeurbanne2022/events/27039422_7427103) annonce « Saint-Saëns, le Carnaval Immersif », Studio 24, **5 décembre 2026 – 3 janvier 2027**, sans certification de 29 séances horaires indépendantes. Le [programme officiel de la Fête des Lumières](https://www.fetedeslumieres.lyon.fr/fr/oeuvre/saint-saens-le-carnaval-immersif) établit **du 5 au 8 décembre, 10 h à 21 h, sur inscription**, ce qui n'établit **pas** un programme complet pour les jours restant jusqu'au 3 janvier. Le module générique de regroupement représente désormais ce cas par `partial_continuous_period_for_editorial_review`, sans création de carte ni invention de séances.

Cette lecture publique de pages et du miroir **n'est pas** une lecture authentifiée de l'API v2. Le retour API de l'événement, la licence et son concédant, le type exact des créneaux, l'identité de l'agenda et le statut à l'instant de lecture restent à vérifier avec une clé `oa_pk_` accessible uniquement sur runner approuvé. Il serait faux de déclarer le smoke test v2 « live réussi » ici.

### Nouveau diagnostic en lecture seule

`scripts/ptitesondes_openagenda_v2_live_smoke.py` reçoit uniquement un lot borné (maximum 12 cas) dans un fichier **éphémère hors Git**. Pour chaque UID il lit le miroir ODS de manière exacte ; **seule** une réponse HTTP 200, sans redirection, dont le nombre total et la liste sont tous deux à zéro, prouve `uid_absent`. Toute panne, UID différent, réponse trop volumineuse ou structure malformée reste `unknown/conflicting`. Le script peut ensuite lire la fiche API v2 avec une clé `oa_pk_` passée par variable d'environnement sécurisée ; il réutilise le contrôle de structure v2 et classe les créneaux. Il ne retourne que des **compteurs anonymisés**, avec `approval_granted=false` et `public_writes=0` ; toutes les exceptions sont masquées pour éviter de divulguer la clé ou le backlog.

Exemple de structure du fichier temporaire (valeurs fictives, jamais de clé dans ce fichier) :

```json
[
  {
    "lead": {"external_id": "12345678", "source_url": "https://openagenda.com/fr/commune-test/events/12345678_fete-jeunesse", "title": "Fête jeunesse", "date_start": "2026-12-05", "date_end": "2026-12-05", "city": "Villeurbanne", "venue": "Salle des familles"},
    "reviewed_agenda": {"agenda_slug": "commune-test", "agenda_uid": "919191", "timezone": "Europe/Paris"},
    "registered_venue": {"city": "Villeurbanne", "aliases": ["Salle des familles"], "lat": 45.758, "lng": 4.8998}
  }
]
```

Le script n'est appelé par aucun cron et ne dispose d'aucune capacité de publication. Pour l'utiliser, il faudra d'abord préparer le fichier de cas à partir des dossiers réellement homologués, puis exécuter uniquement depuis un contexte **de confiance hors PR non fusionnée**, avec la clé de lecture du dépôt public déjà disponible en Secret GitHub Actions. Le branchement aux moteurs et l'exécution réelle ne sont pas compris dans la PR. Les tests sont **offline avec transports simulés**, sans secret, sans consommation de minutes sur le dépôt privé et sans déclencheur planifié supplémentaire.
