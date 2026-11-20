# Grosses Ondes — catalogue radio signé : préparation de diffusion v1

**20 novembre 2026 — laboratoire isolé, aucune mise en production.**

Cette branche construit le côté serveur du **premier lot Android** : produire un paquet de catalogue signé que le vrai client Dart peut vérifier. Les cartes Concerts/Festivals et les artistes cliquables restent pour la deuxième mise à jour.

## Paquet généré

Le programme Python tools/radio_catalog_release_packager.py produit un dossier local avec exactement trois fichiers :

    stage-001/
      current.json
      releases/<empreinte-sha256>.json
      release-preview.json

- Le contenu de releases est immuable : nom dérivé des octets SHA-256. Les données d'origine sont conservées octet pour octet, sans réécriture silencieuse.
- current.json contient le pointeur Ed25519 signé : identité grosses-ondes-radio, séquence, date UTC, empreinte, longueur, chemin de la version et identifiant de clé.
- release-preview.json ne contient que les compteurs, empreintes et la mention explicite publicationAllowed=false. Aucun flux, aucune image, aucune clé de production.
- La signature couvre les mêmes lignes UTF-8 que CentralCatalogPointer.signatureMessage dans le code Dart, avec la ligne finale terminée par LF.

## Contrôles avant signature

Une nouvelle version n'est générée qu'à partir d'un catalogue au statut **publishable** selon les règles existantes et le schéma JSON. Sont refusés notamment : stations actives sans flux verified, fiches historiques staging non approuvées, doublons d'identifiants, champs JSON en double, URL locales, logos invalides, réattribution d'alias, disparition d'une station précédemment identifiée ou régression massive sans revue.

Pour signer une édition 2 ou supérieure, le programme exige un **paquet précédent déjà signé et vérifié** à l'aide d'une clé publique explicitement fournie. La lecture des éditions précédentes peut vérifier une version 2 ou 3 sans relâcher la règle : il est interdit de signer une *nouvelle* édition supérieure à 1 sans prédécesseur validé.

Le processus ne dispose d'aucune commande de déploiement. Il n'accède ni au réseau, ni à Infomaniak, ni au Play Store, ni aux autres catalogues.

## Garde des clés

La clé privée Ed25519 doit demeurer **hors de tout dépôt Git et de toute CI publique**. Le programme requiert un fichier de graine privée en base64 de 32 octets, sans lien symbolique, avec des permissions restrictives sur Linux/macOS (0600). Il n'affiche ni la clé ni son contenu.

La clé publique pourra ensuite être intégrée au vérificateur du véritable APK, **après choix et validation du processus de conservation/rotation**. La graine déterministe utilisée par la CI est totalement fictive, volontairement publique et **ne doit jamais être réutilisée en production**.

## Exemple d'exécution locale après qualification

Depuis le dossier radio-catalog-lab :

    python tools/radio_catalog_release_packager.py \
      --catalog /dossier-prive/catalogue-approuve-v1.json \
      --output-dir /dossier-prive/stage-001 \
      --signing-key-file /dossier-prive-hors-git/ed25519-seed.b64 \
      --key-id cle-radio-go-v1 \
      --published-at 2026-11-20T17:55:00Z \
      --offline-stage-only

Les chemins sont des exemples et **aucune clé de production n'a été créée ici**.

Pour les éditions suivantes, utiliser aussi --previous-bundle-dir et --previous-public-key-file afin de vérifier le pointeur et le contenu du prédécesseur. Les sorties existantes ne sont jamais écrasées.

## Vérification croisée Python ↔ Dart

Workflow : .github/workflows/radio-signed-release-staging-ci.yml

- Déclenchement sur la branche isolée de prépublication uniquement. Permissions GitHub : contents read.
- Dépendances Python épinglées. Tests du garde éditorial et du générateur ; test des versions 1 → 2 → 3.
- Génération d'un paquet **synthétique** dans le dossier temporaire du runner.
- Analyse du code Dart puis test du vrai CentralCatalogVerifier sur les octets signés par Python. Toute altération du catalogue ou clé inconnue est rejetée.
- Vérification qu'aucun fichier suivi par Git n'a été modifié et que les sorties restent dans le répertoire temporaire.
- Aucun transfert, aucun secret et aucun artefact média.

CI constatée : https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44780050079 — **SUCCESS**, 37 tests Python, analyse Dart sans erreur, 1 test d'interopérabilité Dart réussi. Aucune publication.

## Avant la première mise à jour sur les téléphones

1. Partir du **véritable catalogue V64 installé**, pas simplement du staging de ~310 fiches ; vérifier toutes les radios et leurs variantes, notamment RADIO BOB!, les favoris et logos existants.
2. Qualifier progressivement les flux et les décisions éditoriales. L'import historique et les résultats Radio Browser ne sont pas automatiquement des stations publishable.
3. Alimenter le futur catalogue depuis la découverte quotidienne par tous les termes métal, hard rock, punk, thrash, death, black, pagan, nu metal, etc. La collecte reste **ouverte aux nouvelles radios**, sans liste définitive d'UUID.
4. Définir l'hébergement HTTPS, les droits d'accès, la clé de signature réelle et une procédure de publication immuable : déposer d'abord releases, vérifier sa présence et son hash, puis seulement remplacer current.json de façon atomique.
5. Brancher le client signé à l'application en mode réversible. Préserver le cache des logos vérifiés par SHA, la lecture en arrière-plan, les favoris et les entrées Android Auto.
6. Vérifier les démarrages avec et sans réseau, le rollback, la taille AAB, le trafic logo et la continuité de toutes les radios sur appareil réel.

**Rien n'a été fusionné, publié ni déployé dans ce chantier.**
