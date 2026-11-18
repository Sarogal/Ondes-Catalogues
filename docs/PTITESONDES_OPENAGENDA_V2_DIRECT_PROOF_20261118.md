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

### Contre-échantillon public en lecture seule (18/11)

Deux autres UID publiquement documentés ont été interrogés avec la **même requête ODS exacte** :

| Identité publique | Résultat ODS | Constat sur page OpenAgenda |
| --- | --- | --- |
| [CINOR, `55943123`](https://openagenda.com/fr/reseau-des-mediatheques-cinor/events/55943123_activite-manuelle-8019889) | `total_count=1`, UID concordant | Atelier du 18/11/2026, 14h–16h heure de La Réunion, 6–8 ans, inscription ; concédant « Réseau de Lecture Publique de la CINOR », Licence Ouverte 2.0 |
| [Bibliothèques de Marseille, `84874552`](https://openagenda.com/fr/bibliotheques-de-marseille/events/84874552_decouverte-des-services-en-ligne-des-bibliotheques-3983726) | `total_count=1`, UID concordant | Atelier du 12/11/2026, donc passé au 18/11, non publiable comme sortie future |
| [Villeurbanne, `27039422`](https://openagenda.com/fr/villeurbanne2022/events/27039422_7427103) | `total_count=0` | Exposition continue à regrouper, horaires officiels uniquement pour une sous-période |

Ce contre-échantillon établit que le fallback doit distinguer **absence réelle** et **fiche déjà présente dans ODS** : l'API directe n'est pas un second vote indépendant qui permettrait de supprimer la preuve de source, les restrictions de catégories ou la déduplication. Les pages OpenAgenda ont été consultées sans clé, **pas** les réponses API v2 authentifiées. Les âges, horaires et conditions ici sont des observations de fiches publiques à revalider à la date d'une éventuelle publication, jamais des attestations d'organisateur indépendantes.

## Vérification organisatrice générique et inventaire des agendas — suite du 18/11

### Sources organisatrices sans exceptions événementielles

Le module `scripts/ptitesondes_openagenda_v2_organizer_bridge.py` réutilise directement les contrôles de page HTML officielle du moteur national `ptitesondes_family_national_source_preflight.py` (titre, ville, lieu, public familial, date et heure). Il ne rajoute **aucune URL OpenAgenda d'événement** en allowlist. Le domaine de l'organisateur et l'URL exacte doivent provenir d'un registre **indépendamment révisé**, et le contenu HTML doit être récupéré séparément à cette URL exacte (HTTPS, limite de taille, sans redirection par le client appelant).

- Une séance par jour doit présenter sa **date et son heure dans le même bloc visible** de la source organisatrice ; deux horaires ne doivent pas être artificiellement assemblés à partir de deux blocs.
- Les termes explicites « adultes uniquement », « public adulte », « réservé aux adultes » et équivalents interrompent la preuve, **même si le titre de l'événement mentionne des enfants**.
- Un événement sur plusieurs journées sous un UID unique reste réservé au contrat de regroupement : cette voie ne peut pas fabriquer des fiches quotidiennes.
- L'absence de lien vers la page **racine de l'agenda** sur le site organisateur ne bloque plus **le diagnostic de routage** lorsqu'une page d'organisateur de confiance documente la séance exacte. L'UID, le slug d'agenda, la géolocalisation, la période, l'absence prouvée dans ODS et l'historique doivent néanmoins toujours concorder.
- La fonction `dry_run_first_party_fallback` calcule la preuve organisatrice à partir des **mêmes données** OpenAgenda et de la source officielle, sans croire un booléen provenant du backlog. Le résultat reste un **candidat aux vérifications restantes**, jamais un patch ou une approbation.

Ce traitement réduit la dépendance à une correspondance `page institutionnelle → racine OpenAgenda`, sans supprimer la condition indépendante d'une source institutionnelle ou organisatrice réelle. Il ouvre une voie générique aux ateliers, lectures, cinémas et autres sorties, **mais la publication des nouvelles catégories n'est pas encore raccordée**.

### Source registry : les 16 UID restent à authentifier

La route authentifiée de consultation d'un agenda est `GET /v2/agendas/{agendaUID}` selon https://developers.openagenda.com/configuration-dun-agenda/. Elle renseigne l'UID, le slug, le titre, l'URL auto-déclarée et parfois le statut `official`. Ces **métadonnées OpenAgenda ne sont pas une preuve indépendante du propriétaire ou d'un programme**, même si le bit `official=1`.

La fonction `read_direct_agenda_v2` effectue cette lecture sans redirection, avec `key: oa_pk_...` en **en-tête**, une taille et un délai limités, et une identité UID/slug exacte. L'outil manuel `scripts/ptitesondes_openagenda_v2_agenda_census.py` l'applique aux UID du fichier approuvé `Sarogal/PtitesOndes/automation/sources.json` et produit uniquement des **comptages anonymisés** :

- agendas configurés et identités API cohérentes ou non ;
- drapeau `official` seulement informatif ;
- existence éventuelle d'un site de référence auto-déclaré à examiner ;
- agendas indisponibles ou à visibilité restreinte ;
- **zéro organisateur homologué, zéro licence examinée, zéro approbation ou écriture** à ce stade.

Les 16 UID listés dans la configuration sont réels ; aucune identité institutionnelle n'est affirmée automatiquement. Aucune lecture API v2 authentifiée n'a pu être exécutée depuis la PR non fusionnée : pour éviter d'exposer le secret, l'exécution doit se faire dans un contexte de confiance, **jamais dans le code d'une branche PR susceptible de changer**. Les résultats des tests simulés sont clairement distingués des données API live et des publications.

Aucun changement dans `ptitesondes_candidate_promotion.py`, `merge_policy.py`, les catégories publiques, les catalogues, le site Infomaniak, les crons et Grosses Ondes.

## Raccordement DIAGNOSTIQUE au prévalidateur public existant — 18/11 après-midi

`scripts/ptitesondes_candidate_promotion.py:evaluate()` importe désormais `reconcile_backlog()` et joint le rapport `openagenda_v2_readonly_funnel` **uniquement à la sortie de diagnostic privé existante**. L'interface `public_run_summary()` conserve sa liste blanche numérique historique et **n'expose pas ce bloc**, les URL, les UID, les titres ou les villes dans les logs du runner public. Les fonctions `permitted()`, `registry_location()`, `covered_by_published_range()` et `merge_policy.byid()` restent les autorités de validation préexistantes.

Les compteurs savent différencier : UID uniques / couples UID-date / pistes brutes, plusieurs collecteurs sur le même UID, slugs d'agendas syndiqués, conflits de titre ou de plusieurs URL pour un collecteur, UID multi-jours, lieux GPS non vérifiés, séances déjà publiées et UID d'un seul jour seulement **éligibles à une vérification supplémentaire**. Une occurrence affichée sur un seul jour FUTUR mais appartenant aussi à un UID portant une date PASSÉE dans le backlog reste classée multi-jours. Le classement **ne consulte pas de nouvelles API** et n'admet rien.

### Taille de l'échantillon réellement observé dans le backlog privé

Lecture du backlog de la branche privée `automation/ptitesondes-intake` le 18 novembre 2026 :

| Indicateur agrégé | Comptage |
|---|---:|
| Pistes au total | 434 |
| Pistes futures (jour >= 18/11/2026) | 368 |
| UID OpenAgenda distincts dans les pistes futures | 196 |
| Couples UID/jour dans les pistes futures | 338 |
| UID représentés sur plusieurs jours futurs | 28 |
| Pistes futures appartenant à ces 28 UID | 170 |
| Slugs OpenAgenda des liens futurs | 55 |
| Agendas explicitement configurés dans `automation/sources.json` | 16 |

Les 55 slugs ne sont pas 55 organisateurs vérifiés, et les 196 UID ne sont pas 196 fiches admissibles. Il ne faut surtout pas transformer les 170 répétitions multi-jours en sorties quotidiennes fictives, ni prendre deux miroirs du même UID pour deux sources indépendantes.

### État, limites et suite technique

Le branchement concerne uniquement le **reporting de la prévalidation** ; le flux ancien reste inchangé : lecture du backlog privé, interrogation ODS existante, consultation de page officielle, dossier privé, contrôles GPS et historiques. Le point critique est encore l'authentification API v2 de l'UID absent du miroir, l'identité du bon agenda (notamment lors des syndications), la source organisatrice indépendante, la licence par événement, le droit d'accès, la catégorie et la déduplication. Le code de la PR ne branche aucun de ces rapports au publisher et ne change aucune catégorie de `merge_policy`.

Une fois un contexte de confiance pour la clé `OPENAGENDA_READ_KEY` confirmé, exécuter le recensement des 16 agendas et un échantillon borné d'UID prouvés absents d'ODS ; les résultats restent **anonymisés**. En parallèle, faire homologuer un registre à identités d'agendas vérifiées par liens institutionnels exacts et prévoir l'extension ultérieure aux autres slugs. Aucun nouveau cron de dépôt privé n'est nécessaire pour cette étape.
