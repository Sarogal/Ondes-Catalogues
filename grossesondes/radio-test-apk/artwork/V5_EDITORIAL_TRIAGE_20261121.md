# Grosses Ondes — qualification v5 des logos (TEST, 21/11/2026)

**Documentation de développement seulement.** Aucun catalogue signé actif n'est modifié.

## Preuves GitHub Actions

- Réconciliation 310 radios : https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44921337192
- Huit lots de vérification SHA-256 : https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44921656445
- Lot initial de neuf logos TEST : artwork/releases/b85a4ddc27783e2a242747924f28a5438f1fb8d5adb6500c28126a90e588235d.json (non activé).

## Synthèse issue des archives originales

- 310 stations historiques, dont 257 associées à des références v5.
- 232 URLs distinctes, 153 images techniquement validées, 79 URLs non validées.
- 170 UUID historiques associés à des octets contrôlés.
- 69 stations sans URL de logo initiale bénéficient d'une image techniquement validée.
- Parmi ces 69, **9 disposent déjà d'une revue visuelle TEST antérieure et leur SHA-256 est strictement identique** : ne pas refaire inutilement le travail réalisé.
- Les **60 autres restent éditorialement non approuvées**.
- Sept entrées DrGnu utilisent des images dont le chemin contient bob_ ; cinq de ces sept partagent l'URL avec une fiche explicitement RADIO BOB!. Cela appelle une vérification du canal ou relais, pas une fusion/suppression de radios.
- Trente associations du manifeste déclarent une dimension inférieure à 192 px sur au moins un axe.
- Soixante-deux échecs réseau appartiennent à radcap.ru. Conserver intégralement ces radios et leurs anciens logos.
- Les favicons, images de page et logos de réseau génériques restent suspects jusqu'à qualification.

## Outil reproductible

Le script radio-catalog-lab/tools/assemble_v5_artwork_editorial_queue.py lit la réconciliation, chaque lot SHA, et en option la version TEST du premier sidecar. Il vérifie la couverture complète des lots et des URL, les UUID exacts, les métadonnées SHA, et les indicateurs interdisant la publication. Il produit une file de revue JSON et un CSV des radios prioritaires. Un même SHA peut desservir plusieurs identifiants, mais **ne fusionne jamais les stations, flux ou favoris**.

Le workflow go-artwork-v5-review-evidence.yml télécharge les archives historiques et génère la synthèse non signée sur une branche de développement. Aucune nouvelle image n'est téléchargée par ce workflow.

## Avant signature d'une génération TEST élargie

1. Établir l'identité visuelle exacte des 60 autres logos prioritaires et comparer les meilleurs visuels historiques, sans liste fermée de fournisseurs.
2. Rechercher les fichiers de meilleure résolution et traiter RADCAP indépendamment par backoff.
3. Examiner les décalages entre noms/chaînes et logos de réseaux ou d'hébergeurs.
4. Après qualification explicite image par image, créer une nouvelle génération artwork TEST Ed25519 non active, sans toucher au catalogue radio TEST génération 4.
5. Vérifier Flutter, cache SHA, redémarrage hors ligne et Android Auto sur un APK diagnostique distinct avant activation.

Aucune modification de la production, de Google Play ou du pointeur artwork TEST actif n'est autorisée par cette documentation.
