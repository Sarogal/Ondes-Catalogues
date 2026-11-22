# Grosses Ondes — premier démarrage avec artwork signé v2 (22 novembre 2026)

**Scope : TEST seulement. Ne signe aucun fichier, ne modifie aucun pointeur actif et ne publie pas dans Google Play.**

## Incident évité

Le packager Python et le client Flutter exigeaient auparavant `release_sequence == 1` lorsque la mémoire locale ne contenait aucune génération artwork précédente. Ce comportement bloquait les **installations neuves dont la première version disponible est v2**.

La génération artwork v1 à 9 logos a été placée dans `pending/` mais jamais activée. Or le nouveau lot à 12 logos est un candidat v2. Les téléphones n'auraient pas de snapshot v1 à fournir au vérificateur et la v2 aurait été rejetée même avec une signature Ed25519 valide.

## Contrat corrigé

1. **Lecture, première installation sans cache :** accepter toute séquence entière strictement positive, seulement après vérification complète du contenu SHA-256, de la signature Ed25519, de l'identité `TEST_ONLY`, des UUID, des dimensions et des sources officielles. Cela évite de forcer un passage par une version v1 jamais diffusée.
2. **Lecture, cache précédent authentifié :** rejeter une génération inférieure ou égale à la version mise en cache. L'absence de réseau conserve le dernier catalogue signé.
3. **Émission/signature d'un nouveau catalogue :** pour signer une v2 ou ultérieure, le packager exige explicitement la génération précédente ; il refuse toute signature à partir d'un état inconnu.
4. **Migration append-only :** aucune génération mise à jour ne peut supprimer ou modifier les associations UUID/image/source précédemment signées. Seuls de nouveaux UUID peuvent être ajoutés. Les remplacements graphiques ultérieurs doivent passer par un protocole de migration distinct, autorisant un secours vers l'ancien cache.

Le vérificateur Flutter applique la même règle de continuité sur les UUID et les propriétés techniques (URL, SHA, longueur, MIME, dimensions, révision) des descripteurs précédents. Le packager Python verrouille en plus le dossier source complet.

## Preuve GitHub

[Workflow Python #45005361151](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/45005361151) : **SUCCESS** sur les tests de premier démarrage, rollback, signature malveillante, maintenance du lot v1 et append-only.

La PR privée Flutter liée n'a pas encore de suite de tests exécutée : les runs du dépôt privé échouent avant le démarrage des étapes. Les tests Flutter de premier démarrage, reprise hors ligne, replay de la v1 signée et append-only devront être lancés sur le worktree local Windows.

## Ce qui reste inactif

- Radio TEST : génération **4**, inchangée.
- Artwork TEST : aucune valeur `artwork/current.json`, aucune signature v2, aucune publication.
- Deux aperçus non signés v2 de 11 et 12 logos ; l'aperçu à 12 logos est le candidat retenu pour la recette.
- Aucun remplacement des images historiques, aucun effacement de stations, aucun changement d'identifiants, favoris, streams, Android Auto ou Play Store.
