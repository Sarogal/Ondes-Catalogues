# P'tites Ondes — campagne privée complète des lieux inconnus (20/11/2026)

**Statut : PR de prévisualisation isolée, jamais un scheduler ni une publication.**
Dépend de #526, #506 et #503. Aucun cron, secret, workflow privé,
publication GitHub Pages, catalogue ni code Grosses Ondes n'est modifié.

## Pourquoi

Au snapshot du 20 novembre : 449 entrées privées, dont 149 copies de
collecteurs correspondant à 138 séances distinctes sur 79 lieux inconnus.
Les sept lots de 12/12/12/12/12/12/7 existent dans le préflight. Jusqu'ici,
leur exécution et consolidation nécessitaient des commandes manuelles
distinctes : aucun résultat privé live OA + DILA + IGN/BAN n'a été mesuré.

Le nouvel orchestrateur scripts/ptitesondes_private_venue_campaign.py
permet de lancer **explicitement** une campagne sur un snapshot fixe.
Il refuse de réutiliser un rapport ou de changer de backlog en cours de
campagne. Toutes les données privées restent dans un workspace privé.

## Préconditions

- Clone public de cette branche de PR, en lecture seule.
- Clone privé authentifié **séparé, hors du checkout public**, avec
  automation-intake/ptitesondes/backlog.json et automation/sources.json.
- Dossier de rapports privé préexistant, avec permissions 0700, hors
  checkout public ; aucun rapport de même jour ne doit préexister.
- Clé OpenAgenda **de lecture publique** : OPENAGENDA_READ_KEY, fournie
  uniquement en environnement de runner privé ; ne pas imprimer sa valeur.
- Accès réseau en lecture à OA, DILA, pages officielles, IGN/BAN et Overpass.

## Première vérification : préparation hors réseau

    python scripts/ptitesondes_private_venue_campaign.py \
      --backlog /espace-prive/automation-intake/ptitesondes/backlog.json \
      --private-source-config /espace-prive/automation/sources.json \
      --private-output-dir /espace-prive/rapports-2026-11-20 \
      --day 2026-11-20

La sortie ne contient que le nombre de lieux et le nombre de lots. Aucun
fichier n'est créé, aucune requête réseau n'est émise.

## Exécution réelle : autorisation explicite seulement

Même commande, avec --execute-live. L'opérateur est responsable de lancer
cette commande dans le runner privé autorisé ; cette PR **ne l'exécute pas**.

Le lanceur enchaîne chaque lot, avec
--live-probe --official-municipal-pages --official-address-geocode
--shared-location-evidence. Les flux stdout/stderr des sous-processus ne
sont jamais réémis, y compris en cas d'échec. Les chemins privés, noms de
lieux, UID, coordonnées et URL ne doivent pas être copiés dans la CI publique.

Chaque lot est vérifié et ses rapports sont consolidés par le validateur
existant rollup_private_batches() uniquement après l'achèvement des lots.
En cas de panne ou de changement du snapshot, **arrêt immédiat**, sans
synthèse trompeuse ; les rapports partiels restent uniquement privés pour
un examen séparé. Une nouvelle campagne nécessite un dossier privé neuf.

La synthèse agrégée inclut lieux et séances avec preuve géographique
réutilisable, les lots examinés et public_writes=0. Elle ne certifie ni
les sorties, ni les droits, ni la date de chaque séance.

## Statut et étapes de raccordement

- **Développé** : orchestration privée bornée, sept rapports et consolidation.
- **Testé** : tests adversariaux offline, CI isolée de cette PR.
- **Non encore prouvé** : nombre de lieux réellement corroborés sur 79.
- **Non raccordé** : renouvellement automatique des preuves, pipeline
  événementiel, publication non musicale, nouveaux agendas, lieux sans
  adresse numérotée et surveillance du rendement.
- **Interdit ici** : fusion, activation de workflow de production,
  artefacts publics privés ou modification des catalogues.
