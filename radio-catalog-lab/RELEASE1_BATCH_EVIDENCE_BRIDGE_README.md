# Grosses Ondes — Release 1 : raccordement des lots MP3/AAC aux preuves multi-flux

**20 novembre 2026 — prévalidation hors réseau, sans mise en service, ni signature ou publication.**

## Réutilisation des PR existantes

Cette branche, empilée sur la PR **#515**, reprend **à l'identique** le module
`radio_stream_recheck_ledger.py` et les tests complémentaires de la PR **#517**.
L'objectif est de vérifier leur interopérabilité avant de décider de
l'intégration définitive de ces branches. La PR #517 reste indépendante et
ne doit pas être supprimée, fusionnée ni considérée livrée par cet essai.

La seule nouvelle brique est
`tools/radio_catalog_batch_evidence_bridge.py` : elle rassemble les rapports
issus du **vrai sondeur préexistant** `radio_stream_technical_probe.py`
et les transmet au registre multi-flux en mode explicite
`retain_stream_variants=True`. Elle n'ajoute aucun client HTTP et ne décide
jamais si une radio est approuvée.

## Contrôles obligatoires

- Le plan doit dater du même jour UTC que chaque lot.
- Lots numérotés dans l'ordre, au plus huit lots de cinq radios et au plus
  40 contrôles planifiés par jour, sans UUID répété sur la journée.
- **Correspondance exacte UUID + SHA-256 du flux** entre le plan et chacune des
  réponses du sondeur. Un rapport manquant, incomplet ou remplacé est refusé.
- Aucun rapport ne doit affirmer une certification ou porter des URL/échantillons
  audio bruts. Les rapports issus de sondes ne sont que des indices techniques.
- Une nouvelle URL ne récupère jamais les observations d'une ancienne variante.
  En revanche, les preuves de l'ancienne URL restent conservées dans l'archive.
- Les archives historiques par UUID peuvent être migrées au mode multi-flux,
  sans rétrogradation silencieuse ni perte des anciennes observations.
- Le statut `technicallyQualifiedCount=0`, `publicationAllowed=false` demeure
  obligatoire quels que soient les résultats et leur répétition.

## Parcours d'essai hors réseau

1. Construire un plan avec `radio_catalog_probe_batch_plan.py` depuis
   un catalogue central privé et un rapport de découverte.
2. Faire exécuter **séparément et explicitement**, sur un runner de confiance,
   les lots au sondeur existant (avec ses protections DNS/TLS/SSRF).
3. Conserver les rapports de sondage dépourvus d'URL et d'audio.
4. Combiner ceux-ci **hors réseau** dans l'ordre exact du plan :

```sh
python radio-catalog-lab/tools/radio_catalog_batch_evidence_bridge.py \
  --plan /scratch/release1-plan.json \
  --batch-report /scratch/probe-batch-01-results.json \
  --batch-report /scratch/probe-batch-02-results.json \
  --previous /scratch/last-stream-ledger.json \
  --output /scratch/release1-run-summary-day2.json \
  --ledger-output /scratch/release1-stream-ledger-day2.json
```

Omettre `--previous` pour le premier jour. L'argument `--batch-report`
peut être répété jusqu'à huit fois, dans l'ordre des lots. Le fichier indiqué par `--ledger-output` contient **seulement**
le registre `streamEvidence`, directement réutilisable le lendemain avec
`--previous`. `--output` conserve le résumé et le registre ensemble
pour audit. Les deux sorties sont obligatoirement distinctes et ne sont
jamais écrasées ; l'option `--ledger-output` reste facultative.

## Ce qui reste interdit/non acquis

Ce laboratoire et sa CI ne lancent aucune requête sur les radios réelles.
Pas d'activation du cron, de persistance publique des URL,
d'approbation automatique, de modification d'identifiants, de disparition
de radios BOB! ni de publication de `current.json`. Rien n'est activé
dans le lecteur, les favoris, le cache de logos ou Android Auto.

La qualification future devra compléter ces observations par la stabilité
des flux et les critères éditoriaux génériques, puis résoudre les 27 UUID
admis non rapprochés avant la prépublication signée de la PR #511.
Les scénarios HLS complexes restent dans leur file indépendante.

**Ne fusionner aucune PR sans validation explicite.**
