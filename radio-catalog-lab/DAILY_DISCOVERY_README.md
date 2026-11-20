# Grosses Ondes — Recherche quotidienne de radios (laboratoire public)

**Ce laboratoire ne publie aucune radio.** Il prépare le catalogue radio centralisé de la **mise à jour 1**, indépendamment de l'intégration ultérieure des cartes Concerts/Festivals et des fiches artistes (mise à jour 2).

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

## Validation avant branche principale

Avant tout déclenchement quotidien réel et avant la première mise à jour Play Store, démontrer la stabilité de la recherche, la capacité à différencier les stations réellement nouvelles des 27 UUID historiques encore manquants, la qualification automatique des flux, la sécurité des identités et du cache de logos, ainsi que le mécanisme de signature/rollback. La fusion de la PR n'est **pas autorisée sans validation explicite**.
