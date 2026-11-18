# P’tites Ondes — rattachement institutionnel générique d’agendas OpenAgenda
**18 novembre 2026. Développement de diagnostic isolé, sans activation.**

## Hypothèse structurante

Il est irréaliste de maintenir une exception programmée pour chaque séance
de chaque organisateur national. Une institution peut publier sur son propre
site officiel un lien visible vers la racine d’un agenda OpenAgenda. Ce lien
est un signal **indépendant de la collecte OpenAgenda**, qui permet de
comprendre la relation entre son site et un agenda de programmation.

**Cela ne prouve pas** que l’institution possède toutes les données de
l’agenda, que chaque événement est effectivement organisé par elle, que
les horaires sont exacts, que la licence permet leur redistribution, ni
que la publication dans P’tites Ondes est autorisée.

## Contrat technique

`scripts/ptitesondes_openagenda_v2_institutional_delegation.py` :

1. Prend un registre d'institution fourni **hors du candidat** :
   `institution_host`, `exact_page_url`, `agenda_slug`,
   `agenda_uid`, `timezone`. Le registre doit être maintenu
   par une autorité indépendante et ne peut pas provenir de l'API OpenAgenda,
   d'un lien collecté ou d'un résultat de moteur de recherche seul.
2. Exige que la réponse institutionnelle ait été récupérée sans redirection,
   à cette URL HTTPS exacte (hôte ne figurant pas sur OpenAgenda ou ODS).
3. Recherche un lien HTML visible, avec un libellé explicite
   « agenda / programmation / événements / calendrier / sorties », vers
   **la racine** `https://openagenda.com/<slug>` de l'agenda attendu.
   Les liens vers une fiche d'événement, les URL de redirection, les
   faux sous-domaines, les liens masqués et les domaines homographes sont
   insuffisants.
4. Un résultat positif apporte uniquement
   `institutional_root_link_observed=True`. Il laisse
   `independently_attested_owner=False` et
   `event_session_verified=False`.
5. La deuxième étape
   `diagnose_delegated_calendar_candidate` croise cette observation
   avec les contrôles existants : coordonnées officielles de bâtiment
   et IGN/BAN, identité agenda UID + événement UID, statut, titre,
   date et séances API v2.
6. Même en cas de succès structurel, le résultat indique
   `calendar_referenced_but_event_proof_pending` et exige des contrôles
   distincts pour la preuve de séance officielle, la propriété de
   l'agenda, les licences/droits, l'âge/accès, les doublons historiques,
   la classification et l'approbation de publication.

Le module ne lit aucun secret, ne contacte aucun site et n'écrit aucun
catalogue ni patch. Les sorties publiques sont uniquement des codes fixes,
jamais une ville, une page, une UID ou un lien privé.

## Pourquoi cette piste est utile

Le backlog privé lu le 18 novembre contient 434 pistes, dont 412
avec des URLs OpenAgenda. Ses 368 pistes futures correspondent à 334
couples UID/date distincts ; plusieurs UID couvrent plusieurs séances.

Les sept sources institutionnelles de lieux permanents déjà surveillées
dans `ptitesondes_place_agenda_sources.json` ne correspondent qu'à
**deux pistes futures distinctes** de ce backlog (appariement exact de
ville et alias de lieu, sans attestation indépendante complète).

Cette lacune de couverture motive la création d'un **registre national
d'institutions et de leurs agendas effectivement confirmés**, revu
une fois par source et non une fois par sortie. La présente PR ne
fabrique aucune ligne de ce registre et ne prétend pas avoir vérifié
le rattachement de l'un des 16 agendas OA actuellement configurés.

## Absence d'assouplissement caché

Cette PR **ne remplace pas** le contrat de vérification des séances
indépendantes. Elle ajoute un palier de preuve distinct et chiffrable.
La chaîne de publication existante n'utilise pas ce nouvel adaptateur.

Une décision ultérieure d'utiliser un agenda institutionnel attesté
comme *source officielle* de séance serait un **changement explicite de
politique éditoriale** nécessitant validation, revue des droits et
tests end-to-end. Aucun tel changement ici.

### Préparation du prochain test réel

Exécuter en environnement privé avec un échantillon de sites
institutionnels déjà approuvés, contenant la racine OA, puis mesurer
dans un rapport anonyme combien de couples UID/date deviennent
« identité de calendrier confirmée » et combien restent bloqués par
GPS, horaires, public ou droit.

Ne jamais exécuter un workflow de PR avec les secrets du dépôt privé.
Ne rien fusionner, publier ou déployer sans autorisation explicite.

## Vérification impérative de la provenance de la réponse OA

Un test adversarial a révélé que les données d'une réponse d'événement v2
n'incluent pas systématiquement une preuve de l'UID de l'agenda interrogé.
La fonction de diagnostic exige désormais un **contexte de lecture séparé**
`trusted_api_context` avec la méthode GET, le statut HTTP 200, l'URL
exacte `https://api.openagenda.com/v2/agendas/<agenda_uid>/events/<event_uid>`
et un accès `public_read_only`. Les identifiants de ce contexte doivent
correspondre à l'agenda revu et au candidat.

**Ce contexte doit être produit uniquement par le lecteur API de confiance
dans le moteur privé, lors d'une requête réseau réellement réussie** :
les champs fournis par le candidat OpenAgenda ou par ODS ne valent pas
reçu de requête. Le code est un contrat de validation local, pas une signature
cryptographique ; il ne peut certifier sa propre origine si le caller n'est
pas isolé. L'absence de contexte provoque le refus
`direct_api_request_not_independently_bound`, jamais un résultat positif.
La chaîne de publication ne change pas.

## Analyse du backlog réel : deux formats de liens OpenAgenda

Le fichier privé de 434 pistes (SHA de blob
`62133ad94d6c516068f532d6884f95b0dd222179`) a été analysé par
comptages anonymes le 18 novembre :

| Lignes futures (368) | Nombre | Traitement sécurisé |
|---|---:|---|
| URL événement avec UID `/<uid>_<slug>` | 162 | Vérification directe OA v2 + GPS, agenda revu |
| URL miroir historique OpenDataSoft sans UID dans le chemin | 200 | Nouvelle étape de rapprochement API obligatoire |
| Autres URL / fiches non conformes | 6 | Maintien hors voie OA directe |

Les 162 URL strictes présentent **18 slugs d'agenda distincts**, qui ne
sont PAS 18 organismes indépendamment attestés : les alias d'agenda,
les miroirs et les différences de référencement sont possibles.

La fonction `select_pinned_agenda_for_lead` permet uniquement une
sélection depuis un registre de pages institutionnelles maintenu
indépendamment. Elle ne se laisse pas dicter la page officielle par
OpenAgenda ou le collecteur. Si plusieurs institutions revendiquent
un slug, l'identité est mise en attente.

`census_institution_pins_on_private_backlog` est un diagnostic
**anonyme, hors réseau, sans publication** pour rendre visibles les
cas sans épingle, ambiguës, invalides et anciens miroirs à contrôler.

### Traitement des anciens miroirs OpenDataSoft

`diagnose_legacy_ods_authenticated_mapping` reçoit le lien
slug-only conservé **à l'identique**, l'UID explicite de la piste,
l'UID du calendrier présent dans le registre d'institution,
la réponse événement de l'API OA v2 et le reçu de requête établi par
le lecteur privé. Il vérifie l'UID, le titre, la commune et le nom de
lieu, avec exigence d'un GET HTTP 200
`/v2/agendas/<agendaUID>/events/<eventUID>`.

Si ces identités concordent, la sortie indique uniquement
`legacy_identity_api_bound_other_gates_pending`. Elle ne reconstruit
**jamais un faux lien canonical** à partir du slug fourni par ODS.
Le validateur historique `review_direct_v2` et le publisher ne sont
pas contournés. Le résultat conserve :
`canonical_source_url_verified=False`,
`independent_venue_verified=False`,
`independent_event_sessions_verified=False`,
`approval_granted=False`, `public_writes=0`.

Le constat est donc une **opportunité de recouvrement de 200 pistes**,
pas 200 sorties validées. Un futur moteur privé devra faire les
requêtes API réelles, récupérer les preuves officielles et conserver les
règles sur les séries, les droits, l'âge et les lieux.
