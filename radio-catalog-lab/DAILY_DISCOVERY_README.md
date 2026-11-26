# Grosses Ondes — Recherche quotidienne de radios (laboratoire public)

**Ce laboratoire ne publie aucune radio.** Il prépare le catalogue radio centralisé de la **mise à jour 1**, indépendamment de l'intégration ultérieure des cartes Concerts/Festivals et des fiches artistes (mise à jour 2).

## État de référence — 26 novembre 2026

Cette section prévaut sur les descriptions historiques des pilotes ci-dessous. Le laboratoire est toujours isolé et ne publie aucun catalogue utilisable en production.

- PR #474 : branche `feature/radio-daily-discovery-lab-20261120`, fusion soumise à autorisation explicite.
- [Workflow 232](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/45891170407) : 677 tests hors réseau et trois jobs réussis ; état durable `9226a8d`, sur `state/go-radio-discovery-preview`.
- Sur push, la découverte est limitée à douze requêtes Radio Browser ; les collecteurs techniques, éditoriaux et de maintenance peuvent effectuer des sondages réseau bornés. Les budgets, délais et protections sont imposés par le workflow et les modules. Sur dispatch, `run_stream_probes=false` permet d'écarter les étapes de sondage ; la collecte élargie utilise les requêtes tournantes. Le cron 04:17 UTC est dormant hors branche par défaut.
- Le job de persistance seul reçoit `contents: write`, et uniquement sur la branche expérimentale prévue par sa condition. Il sauvegarde les preuves non publiantes et le cache immuable des objets hérités, jamais un catalogue successeur. Les artefacts sont nommés par run et tentative ; le job consomme le nom exact transmis par la collecte. La vérification du parent Git protège les observations des écritures obsolètes ou concurrentes.
- Référence TEST v8 : 296 stations, 285 actives, 358 flux, 320 identifiants historiques, 24 redirections. Les 188 objets graphiques hérités sont disponibles dans le cache durable ; aucun téléchargement de ces objets n'est nécessaire. L'absence d'un logo ne bloque pas à elle seule une admission.
- L'analyseur V7 peut traiter les sources HTML explicites responsives et différées, sans relâcher l'association station/flux. À cette date, aucun nouveau logo n'a été confirmé parmi les 30 stations réelles sans visuel. Les deux stations synthétiques restent exclues de la recherche.
- La qualification V2 est la politique de décision effective du laboratoire ; V3 n'est qu'une comparaison. Les observations positives de continuité doivent provenir de dates UTC distinctes. Les candidats proches de l'admission bénéficient d'un contrôle prioritaire, sans liste nominative.

### Jalons bloquants avant activation

1. Obtenir une admission ou une autre modification admissible sur des preuves réelles, sans fabriquer d'observation. Vérifier les motifs d'éventuel refus indépendant.
2. Contrôler dans `strict-live-release-preview.json` le digest du successeur, la signature Ed25519 avec clé éphémère, la publication atomique simulée, la migration des rapports de maintenance et la resélection du successeur. Une absence de changement n'est pas une preuve de réussite de ces jalons.
3. Préparer séparément le mécanisme de persistance réelle du successeur, le choix de la clé et du pointeur durables, le contrôle de l'inventaire des logos, la reconstruction des rapports de qualification après migration et les tests de reprise/rollback. Actuellement le CLI et les validations de persistance sont verrouillés sur la référence v8 ; le signataire éphémère et le MemoryStore ne sont pas un publisher réel.
4. Préparer le déclenchement quotidien sur branche par défaut et adapter la condition de persistance à l'environnement autorisé. La fusion de #474, la persistance d'un successeur signé et l'activation de publication nécessitent une autorisation explicite. Ne pas modifier TEST v8, l'application, le Play Store ni les autres moteurs pendant cette recette.

**Ne pas confondre tests synthétiques, simulations à partir de preuves réelles, et publication effective.**

---

## Historique des pilotes (20 novembre et états antérieurs)

Les descriptions qui suivent sont conservées pour retracer l'évolution du laboratoire ; les anciens budgets et permissions ne constituent plus le contrat opérationnel actuel.

## Découverte ouverte, pas de catalogue figé

Le fichier `tools/radio_daily_discovery.py` lance des recherches **mondiales** sur Radio Browser, par tags et noms (metal, heavy metal, hard rock, punk, stoner, grunge, rock, etc.). Il ne contient aucun identifiant de station autorisé ou nombre maximum de radios. Les critères de recherche sont ajustables. Une page des résultats récents est interrogée systématiquement, tandis que les pages plus anciennes tournent suivant le jour de la semaine. Les recherches sont bornées pour ménager le fournisseur.

### Familles et sous-genres réellement recherchés

Depuis le 20 novembre, la veille comporte **147 requêtes possibles par tags** et **28 par noms**. Les 12 tags de base sont recherchés chaque jour : metal, heavy metal, hard rock, rock, punk, punk rock, black metal, death metal, thrash metal, trash metal, nu metal et pagan metal ; leurs principales recherches par noms sont également répétées quotidiennement.

Les autres requêtes tournent sur plusieurs jours, dans une enveloppe de **40 recherches de genres/noms par exécution** (plusieurs pages possibles par recherche). Les tests vérifient que toutes les expressions par défaut sont explorées dans une fenêtre d'au plus **10 jours**. Cette limite est uniquement un budget de charge API, pas un plafond de radios admises.

La taxonomie inclut notamment folk/pagan/viking/celtic, symphonic, power, speed, progressive, glam, gothic, industrial, nu/nü/nu-metal, thrash/trash, melodic/brutal/technical death, atmospheric/depressive/blackgaze, doom/funeral/stoner/sludge, grindcore/deathcore/metalcore, mathcore/djent, hardcore/crust/d-beat, punk et variantes, grunge et sous-genres hard rock. La reconnaissance normalise les accents et les variantes de ponctuation pour qualifier des candidats, mais la recherche auprès de l'API garde plusieurs graphies utiles.

**Extension évolutive :** les tags supplémentaires pertinents rencontrés dans les métadonnées des stations deviennent des suggestions dans `suggestedGenreTags`. Au cycle quotidien suivant, le moteur peut réintégrer les tags du rapport précédent parmi les requêtes tournantes, sans modification de l'APK. Cela n'autorise ni la fusion, ni l'admission d'une nouvelle station.

Un identifiant inconnu devient un **candidat** même s'il n'existe pas dans la liste d'admission historique de l'application. Les données Radio Browser (genre, `lastcheckok`, stream, image, pays) ne sont que des indices. Un même nom ou un même flux peut représenter deux stations distinctes : on signale les collisions, **sans fusionner des radios automatiquement**. Le scan n'ouvre jamais les flux.

L'option `--known-uuids-file` peut recevoir un inventaire **dynamique** pour calculer les UUID non reconnus ; sans inventaire, la totalité des résultats est simplement un ensemble de candidats non comparés et **pas un décompte de nouvelles radios**.

## Persistance et absence de suppressions

`tools/radio_daily_candidate_ledger.py` suit, lorsque l'artefact précédent est disponible, les dates de première et dernière observation, ainsi que le nombre de journées distinctes où chaque candidat a été vu. Il n'efface pas un candidat en raison de son absence au scan du jour. Une seconde observation reste une **preuve partielle**, pas une admission automatique.

L'historique est stocké uniquement dans les artefacts GitHub Actions de prévalidation (durée de conservation 14 jours). En cas d'expiration ou de perte de cet historique, il est reconstruit sans supprimer ni modifier les stations publiées. Cette rétention n'est **pas** un registre de production définitif ; une persistance robuste et une vérification des flux seront requises avant activation de l'admission automatique.

## Rapprochement des nouvelles radios

`tools/radio_catalog_daily_candidate_reconcile.py` accepte une photographie du catalogue central v1 et classe les candidats dans quatre catégories : UUID déjà associé, UUID historique à rapprocher, variante/doublon possible, ou candidat non encore rapproché. Ce code se teste ici sur un jeu **synthétique** ; aucun catalogue historique privé ni favori de téléphone n'est copié sur ce dépôt.

**Aucune classe ne signifie « à publier maintenant ».** Il reste à développer un vérificateur réseau générique borné (sécurité DNS, redirections, média audio, recontrôles, identité) et un publisher privé de catalogue signé avec rollback.

## GitHub Actions

Workflow : `.github/workflows/radio-catalog-daily-discovery.yml`.

- Sur la branche de laboratoire, chaque push sur les fichiers ciblés effectue les tests unitaires et un essai réseau restreint (12 requêtes : metal, punk, hard rock, black, thrash/trash, pagan, nu et leurs noms). Les candidats et le registre restent des artefacts.
- `workflow_dispatch` permet une prévisualisation élargie explicitement lancée.
- `schedule: 17 4 * * *` représente une recherche quotidienne vers **04 h 17 UTC**. **Le cron ne se déclenche qu'à partir de la branche par défaut de GitHub** : il n'est pas actif dans cette PR brouillon.
- Les permissions sont limitées à `contents: read` et `actions: read` ; le workflow ne pousse aucun commit, ne publie aucun JSON signé et ne déploie aucune application ou site.

## Qualification des flux : nouveau pilote isolé

La veille peut désormais être suivie d'une **preuve technique limitée à des octets audio**, mais jamais d'une publication automatique.

- `tools/radio_stream_technical_probe.py` : contrôle des URL HTTP/HTTPS, blocage des IP et réponses DNS locales/privées, résolution DNS **puis connexion épinglée sur l'IP publique vérifiée** à chaque saut ; TLS vérifié avec l'hôte original ; 3 redirections au plus, refus des retours HTTPS vers HTTP ; connexion sans proxy et au plus 512 octets d'une seule lecture. Les contrôles identifient des signatures MP3/AAC, FLAC et WAV, ainsi que l'audio Ogg quand un codec audio est reconnu. Les conteneurs Ogg sans codec identifiable, WebM et MP4 restent en `container_pending` : leur seule signature ne prouve pas la présence d'audio. Un simple MIME « audio » n'est pas une preuve suffisante et les playlists M3U/PLS à une seule URL peuvent désormais être suivies **une fois seulement** après revalidation de l'URL et de son DNS ; les manifestes HLS et playlists ambiguës restent en attente, sans téléchargement des segments.
- Les échecs HTTP, DNS, ICY malformés ou format non reconnu restent en `needs_review` ou `playlist_pending` ; **ils ne suppriment jamais une radio**. Les contrôles réseau fonctionnent avec des bornes strictes ; le batch limité tourne d'une journée à l'autre sur les UUID, au lieu de toujours retester les mêmes premiers candidats.
- `tools/radio_stream_recheck_ledger.py` : conserve les empreintes SHA-256 d'URL et les **journées distinctes** où un court échantillon audio a été observé. Une seconde journée avec la même URL marque seulement `repeatAudioSample=true`, pas une station vérifiée ou un droit de publier.
- Les artefacts du précontrôle ne contiennent pas d'audio, ne réémettent pas les URL brutes dans les résultats du vérificateur et n'exigent aucune clé de signature.

Le workflow dispose d'une entrée manuelle explicite `run_stream_probes=true` : **deux contrôles de flux maximum** lors d'un `workflow_dispatch` consenti. Les événements `push` et `schedule` **ne déclenchent pas de requêtes vers les flux** dans ce pilote. Seules les recherches publiques Radio Browser sont automatiquement exécutées sur `push` de branche. Le cron du dépôt reste inactif tant que la PR n'est pas intégrée à la branche par défaut.

**Point de sécurité à franchir avant activation quotidienne de la qualification :** vérification concluante sur davantage de flux réels, HLS segments et formats non standard, stabilité/durée de lecture réelle, qualification éditoriale conforme aux règles génériques historiques, budget de requêtes et fiabilité DNS/redirect prouvés, registre de preuves persistant au-delà des 14 jours d'artefacts et publisher privé signé/rollback. Les échantillons audio ne sont pas une autorisation de diffusion ni une preuve de direct.

[CI de prévalidation : exécution #44679594726](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44679594726) — **90 tests Python sans réseau** (37 découverte/registre, 11 rapprochement, 29 flux sécurisés, 13 observations entre plusieurs jours), plus essai réel sur les seules métadonnées Radio Browser (270 UUID candidats, aucun flux audio ouvert).

## Essai réel isolé : ICY, M3U, PLS et limites de confirmation (20/11)

Les tests ont été étendus à **117 contrôles Python sans accès aux radios externes** dans [CI #44690187807](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44690187807) : 114 tests unitaires/synthétiques et **3 tests de transport utilisant un serveur de radio fictif local**. Aucun catalogue en exploitation n'a été modifié.

- `radio_stream_playlist_preview.py` lit des playlists **M3U et PLS** de taille limitée, identifie une URL unique et confie sa validation au transport épinglé DNS/HTTPS avant tout nouvel accès. Les playlists à plusieurs URL, imbriquées ou pointant vers une adresse privée restent en attente ou sont bloquées ; une seule URL de playlist supplémentaire est autorisée.
- `IcyCompatibleHTTPResponse` accepte une réponse Icecast historique `ICY 200 OK` en conservant la validation de statut HTTP. Les tests couvrent les cas malformés.
- Les manifestes **HLS** sont reconnus mais **pas suivis** vers leurs segments ou variantes. Une playlist HLS accessible ne constitue ni une preuve audio, ni une qualification technique finale.
- La limite reste fixée à **512 octets maximum par réponse** et 3 sauts maximum. Les preuves audio et la notion de « radio en direct » nécessitent encore une validation sur durée, sur plusieurs exécutions et une reconnaissance de codecs plus complète.

Exception d'essai **ponctuel, isolé et non récurrent** : le workflow `.github/workflows/radio-catalog-live-probe-smoke-20261120.yml` a été **ajouté temporairement puis supprimé de la branche après exécution**, sans cron, avec **`contents: read`**. Son rapport de run reste disponible sur GitHub. [Exécution #44689500394](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44689500394) **SUCCESS** : 77 UUID repérés dans quatre recherches limitées, 2 URL de diffusion effectivement sondées, **0 flux techniquement confirmé**. Verdicts : 1 `audio_mime_only`, 1 `not_confirmed_audio`. Aucun statut « audio confirmé » ou publication n'a été émis. Seul le rapport technique dépourvu d'URL et d'octets audio a été conservé.

Le workflow quotidien `radio-catalog-daily-discovery.yml` conserve sa règle **aucun flux sondé automatiquement sur push ou cron**, sauf déclenchement manuel explicite `run_stream_probes=true`. Le workflow temporaire de recette a été retiré : aucune sonde de flux ne sera automatiquement exécutée via cette exception après fusion. Seule l'entrée manuelle explicitement contrôlée demeure sur le workflow principal. Le programme quotidien demeure inactif sur cette branche non par défaut.

### Recette locale intégrée (sans internet)

`test_radio_stream_socket_integration.py` utilise un serveur TCP de test attaché à `127.0.0.1`, uniquement dans la suite de tests. Le résolveur renvoie une adresse publique **simulée**, puis un faux connecteur redirige localement les sockets de ce **test uniquement** ; la sécurité réseau du vrai vérificateur continue à rejeter les adresses privées. Trois scénarios vérifient le code de transport de bout en bout : réponse `ICY 200 OK` avec octets MP3, M3U à URL unique puis ICY, et manifeste HLS ne déclenchant aucun accès à ses segments.

## Validation avant branche principale

Avant tout déclenchement quotidien réel et avant la première mise à jour Play Store, démontrer la stabilité de la recherche, la capacité à différencier les stations réellement nouvelles des 27 UUID historiques encore manquants, la qualification automatique des flux, la sécurité des identités et du cache de logos, ainsi que le mécanisme de signature/rollback. La fusion de la PR n'est **pas autorisée sans validation explicite**.
