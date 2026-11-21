# Grosses Ondes — artwork TEST v2 (12 logos) : redimensionnement vérifié

**21 novembre 2026 — développement isolé.** Cette note décrit un aperçu **non signé**, jamais un manifeste activé.

## Blocage et correctif

La radio **Ritus** a une image de canal lisible `BLACK METAL RADIO RITUS`, que l'API officielle laut.fm rattache au slug exact `ritus`. L'ancien manifeste v5 utilise l'image officielle sous sa forme **redimensionnée** `?t=_640x640`. L'image « canonique » sans ce paramètre ne fournit pas les mêmes octets valides.

Les vérificateurs Python et Dart conservaient la règle historique laut.fm « aucun paramètre URL ». La correction coordonnée n'admet désormais que **un seul** paramètre de forme `t=_LARGEURxHAUTEUR`, à condition que les nombres correspondent précisément aux dimensions du manifeste Ed25519. URL, digest SHA-256, longueur, MIME, décodeur et dimensions restent contrôlés après téléchargement. Les mauvais domaines, ports et paramètres supplémentaires restent rejetés.

**Cela n'impose aucune liste fermée de radios ni de fournisseurs.** Il s'agit uniquement de la relation d'identité spécifique du fournisseur officiel laut.fm.

## Preuve réelle conservée

[Workflow SHA Ritus #44929254839](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44929254839) : **SUCCESS**.

- UUID historique : `681c6fee-8d61-437b-84a4-f96b8fd3422c`
- Source officielle : `https://laut.fm/ritus`
- Image : `https://assets.laut.fm/6523ee49b9dc72e1eb9e2ed32823490f?t=_640x640`
- SHA-256 exact : `076004761be8f6581ae10eefbf6704b13582c494f383e85ebd3b381ea3d33189`
- Octets : **600 273** ; décodeur : **PNG 640 × 640**
- Résultat : SHA, octets, format et dimensions **strictement identiques** à la preuve précédente.

L'archive `go-ritus-640px-fresh-sha-review-only` est sauvegardée pour la revue. La première qualification visuelle de la chaîne est conservée dans `artwork/v5_first_source_visual_review_20261121.json`, avec le statut `can_sign_now=false` : aucune validation éditoriale n'autorise automatiquement l'activation.

## Aperçus comparables, non signés

- `artwork/previews/unsigned-v2-11-logos-20261121.json` : 9 logos initiaux + Radio Beat + Hard Rock Radio FM.
- `artwork/previews/unsigned-v2-12-logos-20261121.json` : les 11 associations **à l'identique**, plus Ritus.

Les deux fichiers ont la séquence envisagée **2** : ce sont des **alternatives à comparer**, pas deux générations successives à activer l'une après l'autre. L'ancien sidecar **v1 de 9 logos** reste le seul réellement signé ; son pointeur est en attente, non actif. Aucun nouveau pointeur signé v2 n'est créé.

Les tests Python refusent les suppressions, substitutions de SHA, changements de dimensions, paramètres arbitraires et régressions de séquence. Le test Flutter correspondant utilise la version v2 à 12 images **signée seulement avec une clé éphémère pendant le test**, pour contrôler les douze UUID et la continuité des neuf premiers.

## Barrières avant toute activation

1. Attendre les contrôles complets de la branche publique et exécuter les nouveaux tests Flutter et l'analyse Dart dans un worktree isolé (le runner privé n'est pas considéré comme une validation).
2. Sécuriser la chaîne de signature TEST Ed25519 sans transférer la clé privée dans GitHub. Signer **uniquement** le dernier aperçu retenu, jamais les deux alternatives v2.
3. Préparer un APK diagnostique `fr.grossesondes.grosses_ondes.centraltest` distinct, sans toucher à l'APK Play Store.
4. Tester cache SHA-256 au premier démarrage, persistance après redémarrage, mode avion, Android Auto et favoris.
5. Activer le pointeur artwork TEST seulement après recette. Garder `grossesondes/radio-test-apk/current.json` sur **génération 4** et `artwork/current.json` absent jusque-là.

Aucun flux, station, UUID historique, favori, catalogue en production, `main` ou Play Store n'est modifié par cette PR.
