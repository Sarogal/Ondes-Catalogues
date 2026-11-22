# Grosses Ondes — contrôle indépendant des sources officielles des logos v5
**21 novembre 2026 — branche TEST uniquement, qualification non publiable.**

## Objectif et origine
Ce lot poursuit la [réconciliation historique des 310 stations](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44921337192), la [validation technique des 232 URL](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44921656445) et les [six planches-contact SHA](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44925794574).

Sur les **69 radios historiques sans URL de logo initiale** ayant une image v5 techniquement contrôlée, **9** possèdent déjà une revue visuelle pour le pilote TEST, avec SHA identique. **60** restent à qualifier éditorialement. Une image du lot DJ 666 Geordieblackcore a changé de SHA depuis le contrôle précédent, elle **ne doit pas être utilisée** sur la base de l'ancienne preuve.

## Nouvel outil
`radio-catalog-lab/tools/corroborate_v5_official_artwork_sources.py` rapproche chaque radio sélectionnée par **UUID historique exact** et **nom exact** avec l'inventaire original. Le contrôle refuse les fiches où une URL de logo existait déjà dans cet inventaire, les lignes déclarées publiables et les candidats sans preuve SHA technique.

Deux voies d'examen sont possibles, **sans liste fermée de radios ni de genres** :

- Pour les pages `laut.fm/{slug}`, interroger l'API officielle avec vérification du slug exact, de la page canonique et du flux officiel (contrôles de l'outil existant `discover_official_laut_fm_logos.py`). Comparer le chemin d'image officiel avec le candidat v5, en signalant que les paramètres URL peuvent changer les octets.
- Pour les autres radios, examiner exclusivement la version HTTPS du site historique selon les garde-fous DNS, taille, redirections et timeout du composant existant. Comparer les références `og:image`, `twitter:image` et `link rel=icon` avec le logo v5. Un fichier sur le même hôte ne suffit pas à établir l'identité du canal.

Tous les résultats conservent `identity_visual_approved=false`, `publication_allowed=false`, `replace_existing_logo=false` et `signed_catalog_created=false`. **Une image mentionnée dans un site officiel peut malgré tout être une image générique** ; cette comparaison ne tient pas lieu de revue visuelle ou de contrôle de la correspondance du flux audio.

Le workflow `go-v5-artwork-official-source-corroboration.yml` relit les preuves SHA archivées et exécute l'analyse par six lots sur des pages publiques HTTPS. Il ne télécharge pas les images originales, ne construit pas de catalogue signé et ne modifie aucun pointeur.

## Confirmations indépendantes préalables
- [Ritus sur laut.fm](https://laut.fm/ritus) : identité de la radio consacrée au black metal confirmée ; image v5 à rapprocher de l'image officielle exacte.
- [Dead To Self Radio](https://deadtoselfradio.com/) et [présentation du changement de logo](https://deadtoselfradio.com/dying.php) : le nom de la radio est confirmé ; le contenu et la version du visuel v5 doivent encore être confrontés au site.
- [Liste officielle des streams RADIO BOB!](https://www.radiobob.de/musik/streams), [Metalcore](https://www.radiobob.de/metalcore-stream) et [Wacken](https://www.radiobob.de/wacken-radio-stream) : plusieurs canaux existent réellement. Les variantes DrGnu/RADIO BOB! gardent **leurs UUID séparés** jusqu'à une vérification des flux et des droits d'association graphique ; même SHA ≠ même station.

## Conditions pour avancer
1. Récupérer tous les rapports de source des six lots. Toute absence ou erreur réseau reste un statut **en attente**, jamais une raison de supprimer un logo historique.
2. Faire la revue de la correspondance station / logo / canal, notamment BOB!, stations utilisant une marque de plateforme, images insuffisamment précises ou trop petites.
3. Pour le logo DJ 666 Geordieblackcore modifié, refaire le contrôle des **octets actuels** et la revue avant une nouvelle référence.
4. Ne constituer un nouveau lot signé **TEST** qu'à partir des preuves de source et de l'image exacte revalidée, avec approbation explicite de l'identité visuelle et sans écraser un ancien logo meilleur.
5. Vérifier sur une **nouvelle compilation diagnostique** le cache permanent SHA-256, l'absence de nouveaux téléchargements au redémarrage, le mode avion, les favoris et Android Auto avant activation TEST.
6. Aucune modification de production, Play Store, `main`, flux, UUID, ou des pointeurs radio/artwork durant cette qualification.
