# P’tites Ondes — audit d’autonomie, état vérifié le 18 novembre 2026

**Statut : audit en lecture seule, branche isolée, aucun merge ni catalogue modifié.**
**Verdict : NON, l’autonomie nationale de bout en bout n’est pas atteinte.**

## 1. Preuves et limites des observations

- Branche publique `main` auditée : `dc3530bce0b189e43c1323377c7686048a6a525d`.
- [Catalogue Git](../docs/ptitesondes/sorties.json) : 549 fiches, 364 futures au 18 novembre, `updated_at=2026-11-17T08:49:57+01:00`. Les sept catégories historiques sont les seules présentes.
- [Catalogue Pages réellement servi](https://sarogal.github.io/Ondes-Catalogues/ptitesondes/sorties.json) : même date et même volume (lecture en ligne).
- [Carte du site](https://ptitesondes.fr/sorties.html) : 364 sorties et date 17 novembre visibles en navigateur ; sélecteur territorial présent. Le navigateur a affiché une liste et une carte, mais la traçabilité de chaque marqueur et l’objet `PtitesOndesSortiesStatus` restent à tester automatiquement.
- [Rapport de collecte privé 18/11](https://github.com/Sarogal/PtitesOndes/blob/automation/ptitesondes-intake/automation-intake/ptitesondes/reports/2026-11-18.json) : 48 *appels* aux API, 585 événements examinés, 476 occurrences pertinentes, 16/16 agendas OpenAgenda, aucune source signalée en échec, 434 pistes conservées, zéro nouvelle piste selon le compteur, zéro publication par la collecte.
- [Tableau de bord privé](https://github.com/Sarogal/PtitesOndes/blob/automation/ptitesondes-intake/automation-intake/ptitesondes/reports/dashboard.json) : 0 lot de qualification déclaré pour le 18/11 au moment de la lecture ; ce n’est PAS une preuve d’échec. Le 17/11 : 51 décisions, 1 prévalidation, 50 autres décisions.
- L’étape [synchronisation cloud du 18/11](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44223493953) a réussi **sans exécuter** commit, build Pages ni déploiement : aucun événement admis sur ce run. Le dernier [pont public/privé](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44228003881) était un cycle lieux ; l’étape sorties y était ignorée.

**Publication musicale réellement prouvée :** 13 commits `data(ptitesondes): publier les seuls événements indépendamment vérifiés` ont modifié `docs/ptitesondes/sorties.json` entre le 12 et le 17/11 ; le catalogue est passé de 522 fiches au snapshot du 12/11 à 549 au 18/11. Le [run 44041690960](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44041690960), du 17/11 à 08:49 (Europe/Paris), a réellement commité, construit, déployé et comparé les JSON GitHub Pages. **Le circuit musical publie automatiquement, mais ne couvre ni les 13 nouvelles catégories ni les cinq régions ultramarines.**

Un statut GitHub Actions « success » n’atteste pas d’une publication. Le `null` d’un rapport absent n’atteste pas d’une validation à zéro.

## 2. Architecture réellement active

`automation/outings_intake.py` (privé, main) -> stockage `automation/ptitesondes-intake` (privé) -> `scripts/ptitesondes_candidate_promotion.py` (public main) -> `automation/merge_verified.py` (privé) -> patch privé -> `scripts/run_cloud_sync.py` et `scripts/merge_policy.py` (public) -> commit du catalogue si et seulement si un ajout franchit les vérifications -> GitHub Pages -> `sorties-source-v2.js` (site).

Les lieux permanents suivent `automation/place_discovery.py` / `automation/place_qualification.py` -> `scripts/ptitesondes_place_preflight.py` -> `docs/ptitesondes/lieux.json`. La couche « Lieux pour enfants » n’est pas une catégorie d’événement daté. Le catalogue lieux contient actuellement **7 fiches**, mis à jour le 9 novembre.

Les crons actifs du pont sorties utilisent 07:17, 10:17, 14:17, 18:17 UTC ; lieux 21:37 UTC. Prévalidation sorties 08:40, 11:40, 15:40, 19:40 UTC ; cloud sync 09:20, 12:20, 16:20, 20:20 UTC. Les traitements privés réguliers sont hébergés sur les runners publics. Préserver cette règle pour éviter la facturation de minutes privées.

## 3. Catalogue exact des types

**Publiés, tous musicaux** : `concert` (98), `conte-musical` (122), `spectacle-musical` (102), `eveil-musical` (172), `atelier-musical` (36), `cine-concert` (16), `festival` (3).

**Contrat national non musical uniquement en lecture seule** (`scripts/ptitesondes_family_national_scope.py`) : lecture jeunesse, ateliers numériques, lecture et cinéma, jeux en famille, ateliers créatifs, scientifiques, spectacles jeune public, cinéma jeunesse, sorties nature, fermes/animaux, musées/patrimoine, fêtes familiales, activités sportives — 13 types. Un contrat distinct de publication non musicale (`scripts/ptitesondes_nonmusic_release_contract.py`) ne couvre expérimentalement que les 4 premiers à la Médiathèque Raoul Georges Nicolo du Gosier ; il renvoie toujours `publication_ready=false`.

**Adaptateurs non raccordés au publisher** : `ptitesondes_real_family_source_adapters.py` reconnaît Paris ODS, Montpellier MPT et iCalendar institutionnel, en mode *découverte seulement*. Les PR #360/#364 ajoutent découverte MPT multi-fiches / contrôle par lots, sans admission ni publication.

**Angles morts opérationnels** : cuisine, cirque, théâtre non musical, expositions/installations artistiques, ateliers sensoriels, activités parents-enfants, activités manuelles/scientifiques/sportives et visites patrimoniales ; certains relèvent d’un des 13 types théoriques mais pas de la collecte productive.

## 4. Couverture territoriale : événements futurs au 18/11

| Région | Futurs | Région | Futurs |
| --- | ---: | --- | ---: |
| Pays de la Loire | 74 | Île-de-France | 70 |
| Occitanie | 37 | Auvergne-Rhône-Alpes | 31 |
| Nouvelle-Aquitaine | 26 | Hauts-de-France | 25 |
| Bretagne | 23 | Provence-Alpes-Côte d’Azur | 19 |
| Bourgogne-Franche-Comté | 17 | Normandie | 16 |
| Grand Est | 12 | Centre-Val de Loire | 8 |
| Corse | 1 | Guadeloupe | 0 |
| Martinique | 0 | Guyane | 0 |
| La Réunion | 0 | Mayotte | 0 |

**Cinq** fiches futures n’ont pas de région renseignée ; le total de 359 attribuées + 5 sans région = 364. L’interface reconnaît les territoires ultramarins ; l’absence de fiches dans ces régions est une lacune de couverture / qualification, pas une incapacité cartographique.

## 5. Sources et limites chiffrées

- `automation/sources.json` : OpenDataSoft national + 16 agendas OpenAgenda configurés ; les 48 « sources interrogées » du rapport représentent les **appels HTTP et pages de recherche**, pas 48 organisations indépendantes.
- `automation/outings_intake.py` recherche **14 expressions** musicales/familiales dans les titres ODS, avec **50 résultats/page et au maximum 3 pages/terme**, sur environ 183 jours futurs. La pertinence reste fondée sur des mots-clés musicaux, malgré une exception très ciblée CINOR.
- `ptitesondes_place_agenda_sources.json` : 7 pages de surveillance de programmes permanents enregistrées ; `ptitesondes_place_sources.json` : seulement 2 entrées de sources publiques de publication. Le premier registre n’équivaut pas à 7 agenda publiables automatiquement.
- L’adaptateur Paris ODS exige de vérifier l’attribution et la licence ODbL ; pour chaque agenda municipal, vérifier droits de réutilisation et origine, sans recopier les descriptions protégées.
- Aucun protocole national générique capable de découvrir puis homologuer de nouvelles sources et d’en assurer l’admission complète n’est déployé. L’ajout de ville/agenda impose toujours une configuration ou un code.

## 6. Causes des 434 pistes et limites des compteurs

Le dernier diagnostic privé du 17/11 classe par **premier motif de blocage** : 181 lieux/GPS non reconnus, 186 éligibles au premier contrôle mais non encore approuvées, 36 dates non admissibles au préfiltre, 30 entrées historiques sans `collector` compatible, 1 identité manquante. Total 434. Ces comptes ne mesurent ni l’authenticité ni les événements « récupérables », qui nécessitent un second passage.

Parmi les 51 décisions approfondies du 17/11 : 37 public/indice musical, 8 source/UID, 3 date/heure, 2 autres, 1 prévalidation positive. C’est une **autre étape** ; ne pas additionner ses refus aux 181 lieux manquants.

L’audit exhaustif privé du **12/11**, obsolète pour classer le backlog actuel, a examiné 117 UID/jours : 54 public/musique, 37 source/UID (24 UID non retrouvés dans le miroir ODS, 13 paires canoniques non homologuées), 19 déjà publiés, 4 date/heure, 3 GPS. Il justifie un diagnostic non borné plus récent.

Les hausses du backlog entre jours alors que `new_leads=0` doivent être réconciliées : `reconcile()` reconstitue `waiting` depuis les *patches différés historiques* ET le backlog ; `new` ne compte que certaines entrées découvertes dans le passage courant. Il n’est pas permis d’affirmer « zéro nouvelle information » à partir de ce champ isolé.

## 7. Restrictions confirmées et arbitrages

| Règle/code | Constat | Décision recommandée |
| --- | --- | --- |
| `outings_intake.py:TERMS/is_relevant` | collecte musicale, autres activités quasi absentes | **Améliorer** via adaptateurs génériques OpenAgenda/ODS/ICS/JSON-LD |
| `outings_intake.py:ODS_MAX_PAGES=3` | troncature possible des résultats nationaux | **Améliorer** avec pagination bornée/cursor/rotation et métrique de pages non lues |
| `candidate_promotion.py:permitted` | lieu homologué obligatoire, 181 pistes pré-bloquées | **Améliorer** avec géocodeurs indépendants multi-sources, conservation du garde-fou final |
| `candidate_promotion.py:MAX_FETCH=15` | jusqu’à 4 lots de 15 par jour, 9 lots relevés au 17/11 | **Améliorer** capacité/rotation selon budget mesuré ; ne pas abandonner les preuves |
| `candidate_promotion.py:confirmed_session` | plus de 4 horaires distincts par jour refusés | **Réexaminer** limite arbitraire ; tester multi-séances avant modification |
| `candidate_promotion.py:category_for` | vocabulaire musical/familial strict | **Améliorer** preuve explicite du public + taxonomie versionnée, sans créer une exception par titre |
| `candidate_promotion.py:reconciled_openagenda_url` | paires de syndication épinglées par ville | **Remplacer progressivement** par vérification générique UID/provenance du réseau |
| `merge_policy.py:valid` et `merge` | catégorie doit déjà figurer dans les historiques musicaux | **Créer une voie d’admission vérifiée séparée**, pas élargir l’allowlist silencieusement |
| `nonmusic_release_contract.py` | toujours read-only, approbations manuelles manquantes | **Raccorder** contrat de publication après preuve indépendante et tests site |
| `family_national_source_preflight.py` | source HTML date/heure/lieu/âge exacts, registre indépendant <=65m | **Conserver preuve** ; améliorer extracteurs structurés et gérer les absences légitimes d’âge chiffré |
| `ptitesondes_place_agenda_watch.py` | 5 domaines fixes, uniquement JSON-LD explicite | **Étendre** aux formats ICS/ODS/API agréés sans inventer récurrences |
| `ptitesondes_place_preflight.py:MAX_BATCH=15` | lieu permanent source homologuée requise | **Conserver preuve**, adapter volume et découverte |
| Doublons UID/date + catalogue immuable | prévient republication et correction non autorisée | **Conserver**, mieux diagnostiquer alias et occurrences distinctes |
| Annulés, complets, scolaires uniquement, sources non vérifiées | risques réels pour les familles | **Conserver** les refus sans détourner un indicateur |

Une activité payante ou sur inscription ne doit pas être exclue par principe ; le prix, l’adhésion, l’inscription et le public admissible doivent être attribués à la source officielle. Les bornes d’âge inconnues ne doivent pas être inventées. Les séances scolaires seules restent hors champ.

## 8. PRs non fusionnées

- [#358](https://github.com/Sarogal/Ondes-Catalogues/pull/358) : 4 lieux GPS supplémentaires ; indépendante.
- [#360](https://github.com/Sarogal/Ondes-Catalogues/pull/360) : découverte multi-fiches MPT ; ses ajouts de scripts sont repris dans #364.
- [#361](https://github.com/Sarogal/Ondes-Catalogues/pull/361) : pilote GPS indépendant MPT.
- [#362](https://github.com/Sarogal/Ondes-Catalogues/pull/362) : dépend de #361 ; prévalidation source/GPS.
- [#364](https://github.com/Sarogal/Ondes-Catalogues/pull/364) : dépend de #362 et étend la géographie à 7 bâtiments ; 24 fiches, 24 séances, 15 classées pour revue, 1 prévalidée par les contrôles indépendants, 0 admission et 0 publication.

Comparaison des SHA de quatre fichiers de découverte MPT : `ptitesondes_mpt_listing_discovery.py`, `ptitesondes_mpt_listing_live_smoke.py`, `ptitesondes_real_family_source_adapters.py` et `test_ptitesondes_mpt_listing_discovery.py` ont des blobs **strictement identiques** dans #360 et #364. Ne pas intégrer deux fois ces quatre contenus.

Les comparaisons Git indiquent : `#361 -> #362 -> #364` en avance sur leurs branches de base ; `#364` est aussi en avance de 31 commits sur `main`, sans retard recensé lors de la comparaison. Cela **ne** vaut pas validation de fusion de toutes les PR en une étape. Réconcilier #360/#364 sur les scripts identiques et préserver les tests. #358 peut être intégré séparément après revue. Aucune fusion autorisée ici.

## 9. Automatisations et autonomie par étape

- **Autonome / observé** : lancement des crons principaux, collecte OpenAgenda/ODS et conservation du backlog privé, vérifications bornées, sécurité append-only des historiques, synchroniseur capable de déployer si patch vérifié.
- **Partiel** : gestion des sources et lieux, répartition territoriale, contrôle des doubles, rattrapage des lots de qualification, surveillance des agendas de lieux.
- **Manuel/inopérant pour ce périmètre** : homologation générique de sources, publication de sorties non musicales, admission du projet MPT en brouillon, preuve de publication Outre-mer, contrôles systématiques de l’affichage navigateur à chaque déploiement.
- **Non vérifié** : configuration réelle du service de secours Cloudflare externe et de ses secrets ; le fichier de code existe mais ne prouve pas l’activation du service. Le watchdog public se contente d’auditer ou d’émettre un heartbeat.

## 9 bis. Incident transversal de surveillance vérifié le 18/11

Les sept derniers cycles du workflow `ondes-public-watchdog.yml` consultés ont **échoué** (dont [run 44200950299](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44200950299)). La dernière erreur provient du contrôle `monitoring/ondes_watchdog.php`, pas d'un échec de syntaxe ou d'authentification : journaux « passage programmé absent » sur plusieurs workflows P'tites Ondes et Grosses Ondes. Les exécutions principales interrogées existent pourtant et sont majoritairement vertes.

Le code associe une exécution à un créneau si `created_at` est compris entre `slot - 120 secondes` et `slot + 9 heures` et signale un créneau « absent » au-delà. Le décalage d'un lancement GitHub ne prouve pas à lui seul l'échec du créneau nominal ; le système ne connaît pas le cron d'origine de chaque run à partir du seul champ `created_at`. Les alertes peuvent donc confondre des retards importants avec des absences réelles, mais elles peuvent aussi être légitimes : **aucune conclusion générale « faux positifs » sans rapprochement supplémentaire**.

Correctif transversal distinct à préparer : classifier les alertes par absence confirmée / exécution tardive / rattrapage confirmé, conserver le seuil d'alerte pour ne pas masquer les incidents, comparer une fenêtre élargie sans attribuer un run au mauvais créneau, tester les cas adversariaux et déployer uniquement après validation. Le Cloudflare Worker indépendant de secours existe en code, mais son déploiement et son efficacité ne sont pas vérifiés.

## 10. Critères de sortie avant le 30 novembre

1. Au moins un **événement musical** découvert après activation d’une source, prévalidé, accepté, commité dans Git, servi par Pages puis effectivement visible sur la carte, sans action manuelle, preuves et IDs archivés.
2. Même preuve intégrale pour **plusieurs types non musicaux**, avec vérification du filtre Type et du fuseau horaire ; une simple simulation, PR verte ou fiche MPT « review » ne suffit pas.
3. Au moins un **lieu permanent** nouvellement découvert et ajouté sans modifier sa fiche à la main, preuve GPS + source indépendante, visible sur la couche lieux ; ses rendez-vous datés suivent la chaîne sorties.
4. Preuves d’exécutions réelles sur les cinq territoires ultramarins, ou lacunes mesurées et traitées sans prétendre à la couverture.
5. Compteurs distincts : sources réelles, appels/pagination, découvertes uniques, vérifiées, admissibles, différées, refusées, publiées, Pages cohérent, navigateur cohérent.
6. Un rattrapage authentifié démontré après un cycle manqué et aucun runner privé récurrent réactivé.
7. Pas de faux âges, faux GPS, fausses dates ni publication à partir de booléens de validation autoproclamés.
8. Non-régression sur les 549 fiches musicales, 7 lieux et le sélecteur des six zones cartographiques.

## 11. Travaux de cette branche

Le module `scripts/ptitesondes_autonomy_funnel.py` fournit un **audit de compteurs agrégés** réexécutable à partir des rapports privés et du catalogue public, sans jamais ouvrir le backlog brut ou diffuser les noms/URLs privés. Il distingue explicitement appels API et organisations sources et conserve `automatically_recoverable_count=null` tant que la mesure n’existe pas. Les tests adversariaux `tests/test_ptitesondes_autonomy_funnel.py` contrôlent confidentialité et cohérence ; la CI publique n'a ni secrets ni droit d'écriture.

Exemple, uniquement sur copies locales des deux rapports de la **même journée et du même état** :

```bash
python scripts/ptitesondes_autonomy_funnel.py \
  --collection /tmp/ptitesondes/reports/2026-11-17.json \
  --qualification /tmp/ptitesondes/reports/qualification-2026-11-17-slot3.json \
  --catalogue docs/ptitesondes/sorties.json \
  --date 2026-11-17
```

L’exemple exige des copies cohérentes ; utiliser un catalogue nouveau et une qualification ancienne rend certaines comparaisons historiques limitées. Aucun workflow de production ne l’invoque.

**Actions restantes :** approbation de l'architecture d’admission non musicale, contrat de provenances source et GPS indépendantes réutilisable, intégration des PR dans l'ordre contrôlé, test réel d'un événement complet, puis batterie d’épreuves adversariales sur âge, fuseaux, récurrence, prix, inscription, homonymie, doublons et publication.

**Aucun déploiement Infomaniak, aucune modification de `main`, aucune approbation artificielle, aucune PR fusionnée.**
