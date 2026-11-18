# P'tites Ondes — preuve directe OpenAgenda API v2 (18/11/2026)

**Brouillon. Non connecté aux pipelines de collecte ni de publication. Aucune production modifiée.**

## Problème

Le prévalidateur historique exige d'abord une réponse du miroir OpenDataSoft par UID, alors que des événements publics OpenAgenda peuvent en être absents. Une source extérieure peut contenir l'UID exact et les créneaux : elle doit pouvoir être vérifiée **sans exonérer** les autres preuves.

Le 18 novembre, 40 pistes à 4 lieux GPS représentaient seulement 9 UID distincts. Parmi elles, 29 enregistrements Studio 24 sont le **même UID d'exposition familiale** du 5 décembre 2026 au 3 janvier 2027. La page lue n'établissait pas 29 séances horodatées. Aucune fiche quotidienne ne peut être fabriquée sur cette base.

## Contrat OpenAgenda v2 documenté

- Lecture GET /v2/agendas/{agendaUID}/events/{eventUID}, avec clé publique oa_pk_ dans l'en-tête HTTP key (jamais en paramètre URL) : https://developers.openagenda.com/10-lecture/ et https://developers.openagenda.com/authentification/.
- uid immutable ; state=2 pour publié ; status=1 pour programmé ; timings explicites begin/end ; timezone ; location et rights : https://developers.openagenda.com/evenements/structure/ et https://developers.openagenda.com/lieux/structure/.
- Une fiche OpenAgenda peut être participative : une correspondance API ne prouve **jamais** seule l'identité de l'organisateur ou les droits de republication.

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
