# Grosses Ondes — migration cloud, état initial du 29/10/2026

## Validé
- Deux instantanés de production **strictement identiques au 29/10** sont archivés :
  - `docs/grossesondes/festivals.json` : 123 éditions, schema 1, `generatedAt=2026-10-25`.
  - `docs/grossesondes/festival-history.json` : 170 archives, schema 2, `updatedAt=2026-10-22`.
- Pages public : `https://sarogal.github.io/Ondes-Catalogues/grossesondes/festivals.json` et `festival-history.json`.
- Manifest SHA-256 `docs/grossesondes/reference-manifest.json`.
- Les 123 slugs calendaires et 170 slugs historiques sont uniques. Aucune date inversée.
- La branche privée de collecte est `Sarogal/GrossesOndes` / `automation/grossesondes-intake`.
- Script `scripts/grossesondes_preview.py` : analyse de la veille privée, comparaison des références, détection des changements et refus des modifications historiques. Ne publie jamais.

## En attente : rattrapage des veilles
La veille du 29 octobre envisageait 123 -> 124 éditions, avec **six corrections** : Winter Rising, Cernunnos, AÜTFËST, Fantasmagorik, Vouziers et L'Arsenal ; nouvelle édition **Muscadeath 2027** sans dates. Ce rapport n'est **pas** un patch de publication validé. Vérifier les sources et les valeurs exactes des champs dans les patches de l'automatisation, en conservant les modifications non encore publiées.

La Scène de Fer 2027 figure déjà dans le JSON calendrier avec `showOnMap:true`. Son absence de la carte doit être diagnostiquée sur le **JS actuellement en production**, et non corrigée en effaçant la fiche.

## Accès lecture seule à la collecte
Générer un jeton GitHub fine-grained, propriétaire `Sarogal`, dépôt sélectionné **GrossesOndes uniquement**, permission **Contents: Read-only**. Enregistrer dans les secrets GitHub Actions de **Ondes-Catalogues** sous **GROSSES_ONDES_INTAKE_READ_TOKEN**. Ne jamais exposer ce jeton dans un commit, une issue ou un chat.

Lancer ensuite manuellement le workflow `.github/workflows/grossesondes-preview.yml` (audit uniquement). Les propositions non présentes dans la production sont conservées; aucune publication sans vérification et aucun retour au dépôt `main` ancien.

## Étapes restantes
1. Valider le patch cumulatif produit par la veille et l'audit indépendant de toutes les évolutions de champs.
2. Implémenter et tester une procédure séparée de publication GitHub Pages, avec contrôles spécifiques d'éditions existantes, dates, artistes, prix, lieu/GPS et archives.
3. Obtenir une copie de l'**actuel site Infomaniak en production** pour y adapter le chargement JSON Pages avec retour vers Infomaniak. La copie `website/` du dépôt privé date du 6 octobre et n'est pas une source déployable.
4. Diagnostiquer les éditions présentes dans le JSON mais masquées sur la carte (dont La Scène de Fer 2027).
5. Après confirmation de la carte, activer la publication quotidienne. Tant que ces étapes ne sont pas réalisées, les fichiers Infomaniak restent inchangés.

## Retour arrière
Les deux fichiers publics de référence restent dans l'historique Git. La production Infomaniak, les archives et la carte n'ont pas été touchées par cet import.

## Contrôles et lot candidat du 29/10/2026
- Audit réel des patches terminé vert : [run 40960898516](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/40960898516), 50 tests, 1 ajout, 27 champs proposés, 8 points différés.
- Qualification strictement officielle : [run 40961605030](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/40961605030), **57 tests réussis**, 123 -> **124 fiches candidates** et **170 archives inchangées**. Artefact téléchargeable `grossesondes-candidat-controle`, qui ne modifie aucun fichier de GitHub Pages.
- Ajout candidat : `muscadeath-2027` (annonce officielle de retour, aucune date/ville/GPS et `showOnMap:false`).
- Corrections candidates : `autfest-2027` (cinq groupes sur la billetterie officielle, anciennes notes contradictoires remplacées par une description source-confirmée), `festival-metal-vouziers-2026` (tarifs confirmés par l'office de tourisme).
- Toujours en attente : `winter-rising-fest-2026` (anciens documents tiers montrent Kawir ; remplacement par Aborym à corroborer avant diffusion), `cernunnos-pagan-fest` (20 artistes sur la page officielle, deux supplémentaires dans d'autres annonces, vérifier la source primaire Facebook), `fantasmagorik-fest-2026` (revérifier le détail avant publication).
- **Pas de publication Grosses Ondes** et pas de modification du code Infomaniak. Aucun workflow de synchronisation quotidien Grosses Ondes activé à ce stade.
- Prochain préalable technique : obtenir les fichiers **réellement en production** derrière `https://grosses-ondes.fr/festivals/` (HTML et JavaScript associés), puis réaliser le même chargement Pages avec repli Infomaniak que pour P'tites Ondes. Ne jamais déployer depuis l'ancien dossier `website/` du dépôt GitHub privé.

## Raccordement site + lot pilote vérifiés (29/10/2026)
- Correctif Infomaniak installé par le propriétaire. La lecture HTTP du site montre `app.js` de **99 608 octets** et la page `festivals/index.html` de **9 023 octets**, tailles correspondant au correctif livré, datés du 29 octobre à 22:07:55 UTC. Le comportement réseau réel du navigateur (Pages puis repli) reste à observer dans DevTools.
- Tests locaux du code client : 9 scénarios verts (Pages, repli, schéma, volume, slugs, accès indisponible, La Scène de Fer).
- Workflow `grossesondes-cloud-sync.yml` : **preview** par défaut, publication quotidienne prévue à 10:47 UTC uniquement si la variable Actions `GROSSES_ONDES_CLOUD_SYNC=enabled`; mode `publish` manuel soumis à la même variable. Lecture seule par le jeton `GROSSES_ONDES_INTAKE_READ_TOKEN`.
- Exécution initiale `40964463617` : **68 tests verts**, candidat **123 → 124**; seul `muscadeath-2027` ajouté, et `autfest-2027` / `festival-metal-vouziers-2026` corrigés, **170 archives inchangées**. `deploy` sauté (aucune publication).
- **PORTÉE LIMITÉE DU PILOTE** : le validateur documentaire indépendant n'admet actuellement QUE ces trois sources officielles. Winter Rising, Cernunnos et Fantasmagorik sont volontairement retenus. Toute nouvelle date/édition ou mise à jour autre que celles explicitement admises nécessite l'élargissement des validateurs indépendants avant publication. Ne pas annoncer que l'automatisation générique est terminée.
- Les deux fichiers Infomaniak sont comparés **octet par octet** à leur empreinte initiale avant chaque publication : une modification manuelle nécessite une procédure de réconciliation. Aucune suppression, altération d'archives ou retour à l'ancien calendrier GitHub n'est permis.
- Prochaine validation : vérifier dans Chrome Réseau que `app.js?v=338` et `https://sarogal.github.io/Ondes-Catalogues/grossesondes/festivals.json` sont effectivement chargés ; puis créer la variable `GROSSES_ONDES_CLOUD_SYNC=enabled` et déclencher manuellement `mode=publish`.

## Extension contrôlée du 29 octobre 2026 — 91 tests
- Prévisualisation complète verte : [GitHub Actions 40967253882](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/40967253882) ; **91 tests réussis**, `deploy` volontairement ignoré car déclenchement par `push` en mode preview.
- **Cernunnos 2027** : vérification indépendante des pages officielles `/`, `/groupes/`, `/infos-pratiques/`. 20 artistes affichés et grille tarifaire 2027 admis ; **Fianna Bán et Waldkauz restent en attente** faute de présence sur la page officielle des groupes. Ne pas dire billetterie ouverte, la page « billetterie » contient encore un avertissement contradictoire. Aucune répartition par jour inventée.
- **Fantasmagorik 2026** : le billet HelloAsso est disponible dans un navigateur humain mais refuse la lecture automatisée GitHub Actions ; la correction reste en attente, non publiée.
- **Winter Rising 2026** : la page de son partenaire affiche encore Kawir tandis que d'autres programmations mentionnent Aborym ; pas de modification non corroborée. Les tarifs sont également contradictoires.
- **Validation générique des lineups** : `scripts/grossesondes_generic_roster.py` n'admet que les **ajouts** de groupes explicitement présents sous un en-tête `programmation <année>` d'un **site organisateur déjà présent dans la fiche de référence**. Il refuse suppressions de groupes, changements de dates, prix, annulations, géolocalisations ou toute mise à jour impossible à prouver. Le synchroniseur n'utilise pas les URLs inconnues fournies par la veille privée et limite les sites consultés par exécution.
- **En attente de publication** : la mise à jour Cernunnos sera intégrée par l'exécution quotidienne suivante, sous réserve de succès de la lecture des sources et du contrôle des archives; déclencher `workflow_dispatch mode=publish` si une publication immédiate est souhaitée. Ne pas prétendre à une publication tant que les jobs `prepare` et `deploy` ne sont pas `success`.
- **Limite volontaire** : les reports, annulations, remplacements et changements de lieu/dates demandent encore un validateur spécifique (preuve officielle datée, identité d'édition et changements de GPS indépendamment établis). À défaut, un point reste dans `deferred`.
