# P'tites Ondes — Chaîne de diagnostics indépendants OA v2, GPS et séances

18 novembre 2026 — Branche isolée, **aucun déploiement**.

## But
Assembler sans exception par événement les modules de #379 (institution + JSON-LD Place + IGN/BAN exact + OA) et #384 (séances du site officiel en JSON-LD Event), sans lever les contrôles de publication.

Les fichiers d'origine des deux PR sont conservés ; `ptitesondes_openagenda_v2_joined_evidence.py` constitue un raccordement de **diagnostic pur, hors pipeline actif**, et non une autorisation de mise en ligne.

## Entrées et zones de confiance
- `lead` et `api_event` sont NON fiables pour homologuer une source.
- `reviewed_agenda` est issu d'un registre séparé.
- `reviewed_venue_source` et `reviewed_organizer` doivent provenir de registres validés indépendamment ; le code **ne les construit jamais à partir du lead**.
- `venue_page` et `organizer_page` doivent être récupérés par l'appelant à leur URL épinglée exacte, via transport HTTPS borné sans redirection ; `geojson` via IGN/BAN.
- L'appelant fournit les données à la fonction pure `diagnose_candidate(case, today)`. La fonction ne réalise aucun HTTP, ne modifie rien et ne consulte pas de secret.
- `diagnose_batch(cases, today)` accepte 1 à 60 cas et ne restitue que des compteurs de motifs fixés par le programme.

## Chaîne effectuée
1. Adresse et identifiant de lieu indépendants + géocodage au numéro + écart OA de 65 m maximum.
2. UID, agenda, pays, date, horaires, public, licence déclarative et structure OA v2.
3. Refus des séries UID multi-jours dans le chemin mono-jour, sans fiches artificielles.
4. Séances de l'organisateur confirmées **soit** dans une même unité de texte visible **soit** dans `schema.org/Event` JSON-LD, avec toutes les séances du jour, lieu, commune, date, fuseau et public familial visibles.
5. Compteur structurel anonymisé ; **aucun candidat approuvé ou publié**.

## Portes supplémentaires non franchies
- Propriété indépendante de l'organisateur et de l'agenda.
- Droits de réutilisation du contenu et des visuels.
- Âge exact, conditions d'accès et inscription.
- Déduplication avec l'historique et regroupement multi-jours.
- Classification éditoriale non musicale et autorisation de publication.
- Vérifications publisher, GitHub Pages puis affichage réel dans la carte.

Un résultat `structural_evidence_complete_other_gates_pending` ne doit **jamais** être assimilé à `safe_to_publish`.

## Suite avant toute intégration active
1. Récupérer des données réelles du backlog dans un environnement **privé** : interdiction de placer les candidats ou leurs URL dans des logs d'Actions publics.
2. Construire le sélecteur de sources officielles depuis un registre séparé, avec preuves de propriété et URL d'événements découvertes automatiquement.
3. Évaluer le funnel sur les 9 portes avec déduplication, accès, droit de publication, conditions familiales et catégorie.
4. Réconcilier les modifications des PR #379 et #384 sur une intégration propre, faire passer tous les tests et autoriser explicitement toute fusion / publication.

## Sécurité
La branche est isolée. Aucun workflow périodique, aucune clé, aucun cron, aucun catalogue public/privé ni publisher n'est modifié. Les tests sont hors réseau.

## État constaté sur la collecte réelle du 18 novembre (sans données de candidats)
Ces mesures proviennent des rapports **agrégés** de la branche privée de collecte ; elles ne
sont **pas** le résultat du nouveau raccordement, qui n'a pas été exécuté sur le backlog réel.

| Étape | État mesuré |
|---|---|
| Découverte | 48 sources, 587 événements examinés, 478 séances pertinentes |
| Backlog | 434 pistes enregistrées |
| Admission historique | 223 pistes brutes admissibles avant certaines déduplications, 140 pistes avec GPS non vérifié, 40 avec date/séance problématique |
| Contrôle de sortie (4 créneaux) | 60 décisions ; 31 échecs UID/source, 16 public/âge, 5 horaire/date, 4 déjà publiées, 2 GPS, 2 autres |
| Source OpenAgenda | 16/16 identités API concordantes ; 0 propriétaire indépendamment attesté |
| Séances organisateur | 0 attestation enregistrée au recensement |
| Prévalidation / approbation / publication du jour | 0 / 0 / 0 |
| Catalogue public | 549 fiches dont 364 futures, date déclarée 2026-11-17 08:49:57 +01:00 |
| Nouvelles catégories non musicales dans le catalogue actuel | 0 — catalogue actuel composé des 7 catégories musicales historiques |
| Couverture ultramarine future | 0 dans les 5 territoires suivis |

**Avertissement** : « pistes » et « décisions » ne sont pas des UID uniques et les 60 décisions
ne constituent pas 60 événements distincts. Aucun taux cumulé de passage des neuf portes
n'est prouvable à partir des seuls rapports agrégés. Les 0 attestations de propriété ne prouvent
pas que les pages officielles n'existent pas : la collecte actuelle ne démontre pas encore cette
vérification indépendante.

## Obstacles structurels existants, à traiter dans une PR dédiée
- `ptitesondes_candidate_promotion.permitted()` exige `registry_location(lead)` dès l'admission ;
  le nouveau GPS n'est donc pas encore essayable sur les 140 pistes non géolocalisées.
- `ptitesondes_candidate_promotion.category_for()` ne retourne que les catégories musicales ;
  une exception explicite à un UID/lieu précis confirme une dette de généralisation.
- `merge_policy.valid()` limite les catégories aux valeurs présentes dans la référence
  historique. Le catalogue courant ne comporte aucune catégorie non musicale.
- `ptitesondes_family_national_scope.FAMILY_TYPES` propose 13 catégories familiales génériques,
  mais son audit ne confère aucun droit de publication.
- `ptitesondes_nonmusic_release_contract.py` vérifie encore des séries propres à un lieu du Gosier
  et n'est pas branché au publisher national.
- Les événements qui couvrent plusieurs jours ne doivent pas être développés en fiches
  quotidiennes fictives : créer un contrat explicite de regroupement et de séances.

**Ne pas lever les refus de source/organisateur, accès, droits, identité GPS, horaires et historique.
Tout élargissement des catégories doit être explicite, versionné, testé et validé avant le publisher.**

## Développement complémentaire : découverte générique depuis un index officiel

`ptitesondes_openagenda_v2_organizer_index.py` fournit une première brique
de découverte des pages d'événements **sans liste blanche par événement**.

1. Un registre d'organisateur maintenu indépendamment fournit uniquement un
   `approved_host` et une `exact_index_url` d'agenda institutionnel.
2. L'index est téléchargé par un lecteur fiable, avec URL finale exacte,
   aucune redirection, taille bornée et sans secret.
3. Les liens HTML **visibles** sont analysés. Seul un intitulé exact normalisé,
   hébergé en HTTPS sur le domaine épinglé, peut désigner une page.
4. Plusieurs pages candidates au même titre => refus d'arbitrage. Page absente,
   lien caché, externe ou douteux => refus.
5. L'URL découverte reste **privée dans le processus d'analyse** ;
   le rapport public renvoie uniquement un motif prédéfini.
6. Le site et la page d'événement doivent encore confirmer publiquement
   l'intégralité des séances, le titre, le lieu, la commune, le public.
   Les validations d'identité, droits, GPS, âge, historique et publication
   restent toutes indispensables.

**Limite réelle :** cette méthode couvre les index HTML où le titre apparaît
exactement dans le texte visible d'un lien. Elle ne couvre pas à elle seule
les agendas uniquement JavaScript, les pages de pagination et les API
spécialisées, les titres raccourcis ou les manifestations multi-jours.
Elle n'atteste pas non plus la propriété de l'organisateur. Des adaptateurs
génériques distincts seront requis, sans assouplir les preuves.

## Statistiques complémentaires sur la branche de stockage privée

Lecture agrégée effectuée sur les 434 pistes existantes :

- 412 pistes avec URL sous `openagenda.com`, **qui ne fournit pas** en soi
  une attestation indépendante de l'organisateur.
- 22 autres pistes, qui doivent suivre une procédure propre à leur source.
- 334 couples UID/date futurs distincts, 27 UID présents à plusieurs dates,
  soit 166 pistes futures dans ces séries.
- 7 lieux permanents publics actuellement disponibles pour la réutilisation
  de preuves géographiques, à la date de cette lecture.
- 549 fiches historiques et futures publiées au total ; 364 futures.

Ces comptages ne constituent pas des données de validation finale.
Les vérificateurs réunis ne peuvent pas être exécutés intégralement
sur le seul fichier de backlog : il manque les réponses directes API v2
correspondantes, les pages officielles indépendamment épinglées et les
réponses géographiques IGN/BAN. **Ne jamais fabriquer ces preuves.**
