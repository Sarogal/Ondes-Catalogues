# Grosses Ondes — inventaire et qualification des logos (branche TEST)

**21 novembre 2026.** Ce dossier prépare la centralisation sécurisée des images radio. Il ne contient **aucun logo approuvé pour publication** ni manifeste d'activation. Le catalogue signé TEST reste en génération **4**, fonctionnel sur Tank 3 Pro et Android Auto ; Play Store et `main` restent inchangés.

## Inventaire source
`legacy_v64_inventory.json` contient **310** UUID historiques, dont **168 URL de logo** (130 HTTPS, 38 HTTP) et **142 radios sans URL**. Ceci n'est pas une liste fermée de stations : tous les moteurs doivent accepter des découvertes sans condition de nom, UUID ou domaine préenregistré.

L'audit [GitHub Actions #44896525107](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44896525107) a vérifié **88 images** sur leurs octets (SHA-256, décodeur, format et dimensions), avec 6 groupes de SHA partagés. **222 fiches** exigent encore des recherches, corrections de source ou revalidations. Une image techniquement correcte n'est pas encore nécessairement le vrai logo de la station.

## Découverte croisée

- **Radio Browser UUID exact** : [run #44896880352](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44896880352), 310 UUID interrogés, 262 retrouvés et 103 URL favicon HTTPS candidates, mais **0 ajout de favicon HTTPS** pour les 142 stations qui n'avaient pas de logo.
- **API officielle laut.fm** : [run #44897415589](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44897415589), **20 stations identifiées sans ambiguïté par leur slug**, **19 images réelles contrôlées SHA-256**, dont **17 nouvelles stations sans logo historique**. Correspondance `api.laut.fm/station/{slug}` avec `page_url`, `stream_url` et `images.station`. `Ritus` a son identité officielle confirmée mais son image reste techniquement refusée. Documentation : https://docs.api.laut.fm/.
- **Sites des radios** : exploration `og:image`, `twitter:image`, `link rel=icon` et `apple-touch-icon` en tant qu'indices uniquement. Les anciens sites HTTP ne sont **jamais téléchargés en HTTP** : une tentative HTTPS sur le même hôte peut être testée, sous garde-fous DNS et redirections.

Les outils conservent l'UUID, l'URL d'origine, la provenance, le SHA, les dimensions et le statut de revue. Un même SHA utilisé par plusieurs radios n'autorise jamais la fusion de leurs identités ou favoris.

## Migration client

La branche privée [PR #320](https://github.com/Sarogal/GrossesOndes/pull/320) introduit l'importateur `CentralLegacyLogoCacheImporter`, qui réutilise les anciens fichiers V64 lorsqu'ils correspondent **exactement** à un logo du catalogue signé (SHA, longueur, décodeur, MIME et dimensions). Pas de réseau, pas de suppression de l'ancien cache. Cinq tests ont été intégrés au préflight Windows mais **ne sont pas encore exécutés** sur cette nouvelle version. L'APK TEST déjà installé ne contient donc pas encore cet ajout.

## Conditions avant une nouvelle génération signée

1. Revoir l'association éditoriale de chaque logo (vrai logo de canal vs favicon ou image de marque générique), et préférer le meilleur visuel officiel disponible.
2. Préparer une publication immuable par SHA sans altérer les flux ni les favoris, sans liste fermée pour les nouvelles radios.
3. Ne pas modifier le pointeur actuel `current.json` de génération 4 sans nouvelle qualification et validation sur téléphone et Android Auto.
4. Conserver les stations RADIO BOB!, éviter la fusion automatique des Wacken, corriger la couverture des images et documenter les exclusions techniques.
5. Continuer la collecte de nouvelles radios/logos par sources ouvertes et éditeurs officiels, avec signature et contrôles avant admission.


## Premier lot de 9 logos signés — TEST uniquement, EN ATTENTE (21/11/2026)

Après récupération de 19 images laut.fm et revue visuelle, 9 images 600×600 comportant un nom de radio lisible ont été retenues. Les 10 autres restent en attente (source visuellement générique, petit format ou ancien logo à comparer). Cette sélection n'est PAS une liste fermée de radios.

- Revue par station : `first_visual_review_20261121.json`.
- Corps signé immuable : `releases/b85a4ddc27783e2a242747924f28a5438f1fb8d5adb6500c28126a90e588235d.json` — 9 associations UUID historique -> SHA-256, source first-party, dimensions, MIME, provenance ; aucun flux musical.
- Pointeur Ed25519 TEST : `pending/test-current-v1.json` — signature du contexte propre `GO-RADIO-ARTWORK-POINTER-V1` avec `go-apk-test-20261121`. Les signatures du catalogue radio ne sont pas réutilisables pour l'artwork.
- **Aucun `artwork/current.json` n'existe** ; cette génération artwork v1 n'est donc PAS ACTIVE. Le catalogue radio signé reste à la génération **4**, inchangée. Aucun de ces neuf logos n'est encore envoyé au téléphone.
- [CI de signature du lot TEST #44899379263](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44899379263) : SUCCESS, preuve SHA, Ed25519, anti-rollback, absence de publication et de changement du pointeur radio.
- Outils : `compose_reviewed_artwork_test_manifest.py`, `artwork_release_packager.py` et leurs tests. Le secret Ed25519 TEST n'est jamais envoyé au dépôt.

### Prochaine recette Android

La [PR privée #320](https://github.com/Sarogal/GrossesOndes/pull/320) contient un vérificateur Dart indépendant pour ce manifeste, un client TEST à cache signé persistant et mode hors connexion, un planificateur UUID-only qui n'écrase pas les logos existants, ainsi que des fixtures cryptographiques réelles. **Ces tests Flutter sont ajoutés au préflight Windows mais ne sont pas encore exécutés.** La version APK TEST actuellement installée ne possède pas encore cette évolution.

Avant d'activer le pointeur artwork TEST : exécuter les tests Flutter et l'analyse, raccorder la lecture des images aux deux écrans (Flutter et Android Auto), compiler un nouvel APK de diagnostic indépendant, contrôler SHA/cache/déduplication/ancien catalogue/favoris sur appareil, puis obtenir validation explicite. Aucun merge, aucune production, aucune mise à jour Play Store.
