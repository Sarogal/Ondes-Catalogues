# Grosses Ondes — Release 1: progressive qualification queue (draft)

**2026-11-20 — separate public laboratory, read-only; not an admission or publisher.**

This tool fills the gap between already-developed central identity reconciliation
(PR #474) and technical stream evidence. It deliberately reuses
`radio_catalog_daily_candidate_reconcile.review_candidates` and existing
`radio_stream_recheck_ledger` output. It does not duplicate stream transport,
DNS, TLS, decoder or signing code. It can run with a **private** input catalog
without uploading that catalog into the public repository.

## What it does

- Retains **every** historical GO station and each legacy stream even when
  Radio Browser did not find it today; preserves all RADIO BOB! records.
- Prepares one review task per historical stream and one per freshly discovered
  candidate. The UUID admission list is **never** a closed-world filter.
- Prioritizes MP3/AAC streams, especially legacy playback; HLS remains a
  separate track and cannot block other codecs.
- Matches cross-day evidence **only** when the UUID and exact SHA-256 of the
  original stream URL agree. A URL change cannot inherit an old success flag.
- Distinguishes candidate identities and duplicate risks without merging
  aliases or altering GO IDs. Transport evidence alone **never** certifies a
  live station.
- Emits report items containing stream **hashes** rather than raw URLs.
  No logo, audio, private key, favorite, device data or publication artifact.

## Offline invocation

From repository root, with private catalog input kept outside this repository:

```sh
python radio-catalog-lab/tools/radio_catalog_qualification_queue.py \
  --catalog /private/staged-radio-catalog.json \
  --discovery /scratch/candidates.json \
  --stream-evidence /scratch/stream-evidence.json \
  --output /scratch/release1-qualification-queue.json
```

`--stream-evidence` is optional for the first pass; the historical catalog
input must follow the central v1 shape. `--legacy-ids` can optionally point
to a JSON list of UUIDs still admitted in the old code but missing from the
central snapshot, so they remain explicitly classified for review.

No write-back is provided. The output refuses to overwrite a previous report.

## Interpreting counts and gates

`preservedHistoricalStreamCount` is a **stream count**, not an installed-device
station count. `discoveredCandidateCount` is a scan count, not new radios
published. `transportLaneCounts` is prioritization, not proof of playability.
All output rows say `technicalQualified=false`,
`editoriallyApproved=false`, and `publicationAllowed=false`.

A technical evidence ledger may indicate two successful MP3/AAC observations
on separate days. Those remain **review evidence**, never an automatic edit,
approval or publication. HLS must be independently rechecked without blocking
the MP3/AAC lane.

## Security and release status

Synthetic branch CI performs offline unit tests only. No live probing, cron,
secrets, Infomaniak, Pages, signed `current.json`, Android or Play Store.
Real release still requires complete device-baseline reconciliation, verified
streams and logos, editorial approval, the signed packager PR #511,
Flutter activation/rollback, Android Auto tests and the owner's authorization.

For the 27 historical admission UUIDs, continue using the private
`radio_catalog_coverage_gate.py`, `radio_catalog_uuid_reconcile.py` and
`radio_catalog_triage_preview.py`. Their classification is not a merge plan.

## Nouvelle étape : planification bornée et équitable (20 novembre)

`tools/radio_catalog_probe_batch_plan.py` réutilise **directement**
`build_queue` au lieu de créer un autre classement, et prépare une rotation
par jour UTC des flux MP3/AAC à contrôler. Limites strictes : au plus **40
flux par jour**, découpés en **8 lots de 5 au maximum**, compatibles avec le
sondeur existant. En présence de nouveautés, jusqu'à 20 % de la capacité leur
est réservée. HLS et codecs inconnus n'empêchent pas les contrôles MP3/AAC.

Sur une photographie stable de **339 flux historiques distincts, avec UUID
indépendants**, et 10 nouveautés, la rotation synthétique parcourt les 339
anciens en 11 jours (32 anciens + 8 découvertes par jour). Ce chiffre est une
simulation de planification et **ne représente aucun flux déjà sondé**.
Les contrôles multipliés, les reprises après interruption et les seconds
passages restent à orchestrer et prouver sur l'infrastructure réelle.

Le plan JSON public ne contient **aucune URL de flux** : seulement des UUID,
SHA de flux et références de travail. Si nécessaire, l'option facultative
`--scratch-probe-inputs` génère des entrées intermédiaires réellement
compatibles avec le sondeur existant, uniquement dans un nouveau dossier
éphémère explicitement situé **hors du checkout Git**. Les fichiers bruts
doivent rester privés, ne jamais être envoyés dans les artefacts GitHub,
et être effacés après sondage. Le CLI ne lance **aucune requête réseau**.

Exemple de prévisualisation locale, depuis la racine du dépôt public,
avec catalogue privé accessible seulement sur la machine de contrôle :

```sh
python radio-catalog-lab/tools/radio_catalog_probe_batch_plan.py \
  --catalog /private/staged-radio-catalog.json \
  --discovery /scratch/candidates.json \
  --date 2026-11-20 \
  --max-daily 40 --max-per-batch 5 \
  --output /scratch/probe-batch-plan.json
```

Pour générer **uniquement sur une machine de confiance**, des entrées
temporaires à fournir plus tard au sondeur, ajouter :

```sh
  --scratch-probe-inputs /tmp/go-radio-private-probe-inputs
```

La génération de ces entrées n'exécute aucun sondage. Chaque lancement du
sondeur demandera son option réseau explicite et sera limité à 5 URL.
**Aucun workflow automatique ne consomme encore ces lots.**

**Limites multi-flux actuelles :** une seule URL par UUID est sélectionnée par
jour pour ne pas provoquer de collision dans le registre de preuves existant.
Le registre actuel agrège les preuves par UUID, alors que la future
qualification devra garder les preuves par couple `UUID + empreinte de flux`
pour ne pas perdre l'historique des variantes. Cette évolution est distincte
et obligatoire avant de prétendre qualifier toutes les variantes.
