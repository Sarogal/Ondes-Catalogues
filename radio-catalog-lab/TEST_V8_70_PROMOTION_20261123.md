# Grosses Ondes — TEST central radio v8 : 70 logos SHA-256, signature et promotion

État au 23 novembre 2026 : **prêt à signer localement, non signé et non publié**.
Aucune compilation Android, aucune modification de `main` ou du Play Store.

## Assets intégrés, mais v7 toujours active

- Branche du pointeur TEST utilisé par l'APK :
  `feature/go-radio-test-v2-isolated-20261123`.
- Commit ajoutant exactement les 70 objets image SHA-256 :
  `2e5cc9233439317401f0fba31d10065d89009c84`.
- Tous les objets sont hébergés dans
  `grossesondes/radio-test-v2/artwork/sha256/<sha256>.<extension>`.
- Le pointeur `grossesondes/radio-test-v2/current.json` pointe toujours vers la
  **v7 signée avec la clé `go-apk-test-20261122-v2`**, de contenu
  `f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa`.
- Les 70 images représentent ~5,2 Mo au total ; seuls les nouveaux SHA non
  déjà présents dans le cache du téléphone doivent être téléchargés.
- Le nouveau **catalogue v8 canonical TEST** non signé est
  `radio-catalog-lab/full-staging/UNSIGNED-radio-v8-70-CANONICAL-TEST-SHA-20261123.json`.
  Il comprend 285 stations actives, 259 logos, 26 stations encore sans logo,
  320 GO IDs, 363 UUID historiques de favoris, 24 tombstones/redirections.
  Aucun flux ou autre champ de station n'a été modifié.

## Validation avant signature

- [QA originale 70 SHA, v7 signée → v8](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/45270586413) : SUCCESS.
- [Contrôle des 70 blobs SERVIS sur la branche TEST, et signature éphémère du candidat par le vrai packager](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/45272418633) : SUCCESS.
- Le test n'a pas signé avec une clé TEST réelle et n'a rien publié. La clé
  éphémère de CI ne peut pas devenir celle de l'APK.

## Correctif Windows — CairoSVG / libcairo absente (23/11)

La conversion de sources SVG historiques fait partie de l'audit effectué dans
GitHub Actions, mais **la publication locale v8 ne convertit aucun SVG** :
les 70 objets SHA-256 finaux existent déjà en PNG, JPEG ou WebP sur la branche
TEST. L'import de l'audit SVG est désormais différé et absent du parcours
`publish_go_radio_v8_test.py`. Il ne faut **pas installer CairoSVG, GTK ou
libcairo sous Windows** pour publier ce catalogue.

Si le clone propre `D:\KL_Softwares\Ondes-Catalogues-v8-sign` a déjà été créé,
il suffit d'y récupérer le correctif par `git pull --ff-only`, sans supprimer
ni réinitialiser le répertoire. N'exécuter la publication qu'après le
contrôle préliminaire avec la même clé TEST v2.

```powershell
cd D:\KL_Softwares\Ondes-Catalogues-v8-sign
git pull --ff-only origin feature/go-radio-v8-metalon-3-logos-20261123
py -m pip install 'cryptography>=42,<47' 'jsonschema>=4.21,<5' 'Pillow==11.3.0'
$seed = Join-Path $env:LOCALAPPDATA 'GrossesOndes\RadioTestSigningV2\GO_CENTRAL_TEST_SIGNING_SEED_20261122_V2.b64'
py .\radio-catalog-lab\tools\publish_go_radio_v8_test.py --signing-key-file $seed
```

Une fois cet aperçu signé hors ligne réussi, ajouter `--publish-test` à la
dernière commande pour demander la publication TEST contrôlée. Ne jamais
coller la clé dans PowerShell ni l'envoyer dans le chat.

## Signature locale et publication TEST en un seul processus contrôlé

Cette opération requiert la **graine privée Ed25519 TEST v2 qui a déjà servi à signer la v7**.
Elle reste uniquement sur le PC Windows, jamais dans un dépôt ou un workflow GitHub.
L'outil compare la clé publique dérivée à `TEST_PUBLIC_KEY.b64` et refuse toute clé différente.

Depuis PowerShell :

```powershell
cd D:\KL_Softwares
git -c core.autocrlf=false clone --branch feature/go-radio-v8-metalon-3-logos-20261123 https://github.com/Sarogal/Ondes-Catalogues.git Ondes-Catalogues-v8-sign
cd .\Ondes-Catalogues-v8-sign
git config core.autocrlf false
py -m pip install 'cryptography>=42,<47' 'jsonschema>=4.21,<5' 'Pillow==11.3.0'
$seed = Join-Path $env:LOCALAPPDATA 'GrossesOndes\RadioTestSigningV2\GO_CENTRAL_TEST_SIGNING_SEED_20261122_V2.b64'
py .\radio-catalog-lab\tools\publish_go_radio_v8_test.py --signing-key-file $seed --publish-test
```

Si le dossier `Ondes-Catalogues-v8-sign` existe déjà, utiliser un nouveau
dossier de clone propre, sans jamais réinitialiser ou nettoyer un autre checkout.

Ce processus :

1. Vérifie la clé privée locale contre la clé publique réellement embarquée,
   la v7 signée, les 70 fichiers du TEST, les ID/favoris/redirections et le
   schéma du catalogue. Il signe la v8 et vérifie la signature hors dépôt.
2. Crée un aperçu signé dans un dossier temporaire local hors Git.
3. Ajoute et pousse **uniquement le JSON immuable**
   `grossesondes/radio-test-v2/releases/<sha256>.json` sur la branche TEST.
4. **Vérifie octet par octet son accessibilité HTTPS**, avant d'autoriser la
   mise à jour de `current.json`. Si cette étape échoue, la v7 reste active.
5. Pousse ensuite **uniquement le nouveau pointeur Ed25519** `current.json`,
   sur la même branche TEST. Aucun force-push n'est utilisé.
6. Ne modifie jamais `main`, la production, l'APK Android, Android Auto ou le
   Play Store. Après propagation du pointeur, le téléphone installé doit
   accepter la génération 8 au prochain chargement réseau et conserver son
   cache SHA en mode hors connexion.

Par défaut, l'outil sans `--publish-test` fait **uniquement un aperçu
signé hors ligne**, sans aucune écriture GitHub.

**Ne jamais copier le fichier de clé privée ou son contenu dans un message,
une PR, une issue, un log, un artefact GitHub Actions ou un dépôt.**
