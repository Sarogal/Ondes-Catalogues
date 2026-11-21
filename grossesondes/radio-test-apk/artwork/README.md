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

## Mise à jour : reprise des logos publics v5, SHA et UUID (21/11/2026)

La version installée sur le **Tank 3 Pro** (APK TEST `9fbe6f8`) a passé **86/86** tests Flutter et les recettes utilisateur **5/5 connectées, 4/4 mode avion, Android Auto validé**. Ne pas confondre ce succès avec la migration des logos v5 : le pointeur artwork `artwork/current.json` est toujours **absent** et les 9 logos Ed25519 v1 restent en attente.

**Le lot de 9 logos est seulement le pilote cryptographique.** Nous avons retrouvé sur le site officiel le manifeste **v5 avec 265 associations UUID→image, 232 URL distinctes** (v4 embarquée : 261/228). Les **9 identités du pilote existaient déjà** dans l'ancien manifeste. Le catalogue V64 contient 310 radios, dont 142 sans URL de logo dans le bootstrap ; **120 de ces 142** ont déjà une URL dans le manifeste v5. Aucune association ne doit être jetée à cause d'un hôte ou groupe inconnu.

- **Réconciliation CI [#44921337192](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44921337192)** : 5 tests, 310 identifiants historiques, 265 entrées v5, 257 associations par UUID exact, 8 entrées de manifeste hors inventaire historique. Le rapport archive **seulement des candidats non approuvés**, jamais des flux ou publications.
- **Audit SHA/decoder CI [#44921656445](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44921656445)** : 8 lots réussis, **232 URL distinctes vérifiées, 153 images techniquement acceptées, 79 refusées** ; chaque URL téléchargée au plus une fois dans ce lot. Parmi les 257 radios historiques avec référence v5, **170** ont une image à octets contrôlés. **69 des 120** qui n'avaient pas d'URL initiale disposent d'une image techniquement vérifiée. Cela ne signifie PAS encore 69 identités visuelles approuvées.
- Analyse exacte des 79 refus : **62 erreurs URL réseau, toutes sur radcap.ru**, déjà touché par un échec TLS connu ; **15 refus de format/qualité/sécurité de l'image** (`InventoryError`), **2 erreurs HTTP**. RADCAP et ses stations **ne sont pas supprimés** ; les caches anciens et le fallback de genre restent indispensables.
- Le validateur et le packager Ed25519 acceptent maintenant des sources de radios officielles **de tout domaine HTTPS public**, avec des preuves signées de provenance et de revue visuelle. Les contrôles stricts historiquement applicables aux neuf images `laut.fm` sont conservés. Voir [CI de signature v1 + tests sources nouvelles](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44921132850).

**État de sécurité :** rapports et listes v5 non signés, aucune image v5 activée automatiquement, aucun téléchargement de logos déclenché par l'APK installé ; aucun changement sur `radio-test-apk/current.json` génération 4, ni sur l'application publique. Pour migrer les 153 images techniquement vérifiées, il reste à établir une preuve d'identité du canal et choisir un logo de qualité pour chaque UUID, puis produire un manifeste TEST Ed25519 de génération suivante et vérifier la continuité des logos déjà visibles.
