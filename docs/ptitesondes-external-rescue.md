# P'tites Ondes — secours indépendant des schedules GitHub (issue privée #53)

**Statut : prêt dans le dépôt public, NON ACTIVÉ tant qu'aucun Worker externe n'est déployé.**
L'absence totale de `schedule` GitHub nécessite un **autre ordonnanceur**. La PR de rattrapage #230 seule ne peut pas déclencher une collecte.

## Architecture sans coût récurrent privé

1. Cloudflare Workers **Free** déclenche `scripts/ptitesondes_external_rescue_worker.mjs` par ses propres Cron Triggers UTC.
2. Le Worker POST sur l'API GitHub `workflow_dispatch` de **Sarogal/Ondes-Catalogues** (dépôt PUBLIC), avec un jeton limité à ce dépôt et à **Actions: Read and write**.
3. Pour les sorties : `cycle=outings`, `mode=write`, `recovery=catchup`. Le moteur public réalise une collecte, calcule les créneaux déjà échus et non attestés, valide au maximum **4 × 15 pistes** avec conservation privée de chaque rapport et patch cumulé. Les anciennes collectes réseau perdues ne sont jamais présentées comme réalisées.
4. Pour les lieux : `cycle=places`, `mode=write`, `recovery=none`, selon le moteur privé actuel.
5. La publication séparée n'est jamais contournée. Aucun accès direct à `Sarogal/PtitesOndes` n'est remis à Cloudflare.
6. Les exécutions GitHub habituelles restent actives ; `concurrency.queue: max` et les rapports de lots bornent les doublons de qualification. Un secours peut cependant ajouter une collecte réseau lorsqu'un `schedule` tardif a déjà réussi.

Horaires de secours (UTC) :
- `47 7,10,14,18 * * *` : 07:47 / 10:47 / 14:47 / 18:47 UTC, 30 min après les crons Sorties.
- `57 21 * * *` : 21:57 UTC, 20 min après le cron Lieux.

Deux définitions Cron Triggers (sur la limite gratuite de **5 par compte**) couvrent cinq passages quotidiens. Le Worker expose une route HTTP inerte (404), **pas d'URL de déclenchement publique**.

## Installation nécessitant une action du propriétaire du compte

- Vérifier dans la console Cloudflare la disponibilité de **Workers Free**, sans souscrire à un forfait payant.
- Déployer le module JS Worker depuis le fichier public `scripts/ptitesondes_external_rescue_worker.mjs` avec les **deux crons exacts** ci-dessus. Si les crons sont configurés depuis le tableau de bord, ne pas les remplacer ensuite par une configuration Wrangler divergente.
- Créer sur GitHub un **fine-grained PAT** sur `Sarogal/Ondes-Catalogues` *uniquement*, permission dépôt **Actions: Read and write** (Contents reste en lecture seule implicite). Choisir une date d'expiration et planifier sa rotation. Ne jamais utiliser un PAT global `repo` ni le secret d'écriture vers le dépôt privé.
- Stocker le PAT seulement dans **Cloudflare Worker → Settings → Variables and Secrets → Add → Secret** sous le nom `GITHUB_DISPATCH_TOKEN`. Ne jamais le communiquer dans un chat, une issue, un fichier versionné, une URL ou un log.
- Contrôler les **Cron Events** Cloudflare puis, côté GitHub, vérifier le nouvel événement `workflow_dispatch`, le mode privé write, les rapports `qualification-AAAA-MM-JJ-slotN.json` et l'absence de publication non vérifiée.
- Ne jamais interpréter le `204` de l'API GitHub comme la réussite finale du workflow : ce code signifie seulement que le lancement a été accepté. Contrôler le statut de l'Action et ses étapes.
- Désactivation immédiate : supprimer les deux Cron Triggers ou désactiver le Worker et révoquer le PAT. Cela n'affecte pas les 5 crons GitHub existants.

**Limites :** un secours externe indépendant réduit fortement le risque de journée vide, sans garantie mathématique face à une panne combinée Cloudflare/GitHub ou une révocation du token. Les nouveaux horaires de secours n'augmentent ni les minutes des runners privés ni les permissions du Workflow public. Aucun paiement ne doit être engagé.

**Tests hors réseau :** `python -m unittest discover -s tests -p 'test_ptitesondes_schedule_catchup.py' -v` puis `node --test tests/test_ptitesondes_external_rescue_worker.mjs`.
