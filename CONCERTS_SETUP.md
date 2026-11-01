# Grosses Ondes — synchronisation Concerts par GitHub Pages

## État vérifié le 1er novembre 2026

- Source de la carte destinée à devenir prioritaire : **https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json**.
- Référence publique GitHub Pages : `docs/grossesondes/concerts.json` : **127 concerts, 53 salles, 193 artistes**, version v0.6.
- Archive immuable : `docs/grossesondes/concerts-reference.json`, copiée à partir de la même production Infomaniak. Les tests interdisent de modifier ou supprimer l'une des 127 fiches initiales, ou l'une des 53 salles et 193 artistes initiaux.
- Découvertes conservées dans le **dépôt privé** `Sarogal/GrossesOndes`, fichier `automation/concerts/intake/registry.json`. Les propositions ne sont PAS publiées automatiquement.
- File d'approbation privée `Sarogal/GrossesOndes/automation/concerts/approved.json`, initialement vide. Une fiche ne peut être transférée vers le catalogue public qu'après décision explicite `approved` et pièces justifiant une annonce officielle.
- Workflow public de validation/publication : `.github/workflows/grossesondes-concerts-cloud-sync.yml`. Exécution quotidienne 12:13 UTC et exécution manuelle. Un changement dans le workflow ou le fichier de référence peut déclencher un redéploiement GitHub Pages du catalogue déjà public, **sans ajouter de concert**.
- Mode `preview` par défaut. Une publication de **nouveaux événements** ne devient possible que lorsque la variable du dépôt `GROSSES_ONDES_CONCERTS_CLOUD_SYNC` est exactement `enabled`, que le mode effectif est `publish`, qu'un nouvel événement est approuvé et que tous les contrôles passent.
- La clé privée déjà utilisée pour les festivals, `GROSSES_ONDES_INTAKE_READ_TOKEN`, permet de consulter les approbations privées. Ne jamais divulguer ce secret.
- Une approbation exige un lieu déjà présent, des IDs d'artistes valides, une date future, des genres documentés, un statut confirmé, un lien HTTPS officiel et un enregistrement de vérification indépendant. Les doublons probables à même lieu/date/artiste sont bloqués. Les archives et les fiches préexistantes restent inchangées.

## Raccordement à Infomaniak — **une seule manipulation ponctuelle**

La page `https://grosses-ondes.fr/concerts/` utilise encore `concerts/catalogue.json` local. Il faut adapter **uniquement le chargement de données de `/concerts/app.js`**, sans écraser le reste du site, pour :
1. Tenter `https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json` avec `cache: 'no-store'`.
2. Vérifier que le schéma `schemaVersion:1`, le mode `preview-public-unlisted`, tous les identifiants et le contenu sont conformes, avec les minima 127 événements, 53 salles et 193 artistes.
3. En cas d'échec réseau, CORS ou validation, charger **le JSON de secours `catalogue.json`** actuellement sur Infomaniak.
4. Modifier la version de `app.js` dans `/concerts/index.html` pour que les visiteurs ne gardent pas l'ancien JS en cache.

**Ne pas remplacer `/concerts/index.html` et `/concerts/app.js` par les fichiers `website/` du GitHub privé** : ils peuvent être antérieurs au site actuellement publié. Télécharger au préalable les **deux fichiers réels depuis Infomaniak WebFTP** et appliquer `automation/concerts/patch_site_loader.py`, qui refuse de travailler si le code de chargement a changé depuis l'audit. Sauvegarder les originaux avant tout envoi.

À ce stade, la création du JSON sur GitHub Pages n'implique **pas** que le navigateur utilise déjà ce JSON. Tester dans Chrome, onglet Réseau, la présence de la requête GitHub Pages, puis la carte, les filtres et le repli si la source GitHub est volontairement indisponible.

La rubrique `/concerts/` reste masquée de la navigation générale et en `noindex,nofollow` jusqu'au lancement annoncé.

## Ce qui reste à automatiser

Le moteur de veille sait découvrir et archiver les propositions. Le validateur indépendant par salle / événement doit encore être étendu pour transformer sans intervention quotidienne les propositions fiables en approbations. Tant qu'une annonce n'est pas suffisamment prouvée, **aucun nouvel événement ne rejoint la carte**, même si l'exécution GitHub Actions est verte.

**Ne jamais interpréter un nombre de candidats comme un nombre de concerts nouveaux validés.**
