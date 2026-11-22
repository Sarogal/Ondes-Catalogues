# P'tites Ondes — balayage NATIONAL de l'index OpenAgenda public (prévisualisation)

**20 novembre 2026 — développement isolé, aucune exécution de production**

## Point de départ

La route officielle documentée `GET https://api.openagenda.com/v2/agendas` donne accès aux agendas **publiés et indexés** d'OpenAgenda. Les paramètres documentés incluent `size` (maximum 100) et le curseur de pagination `after[]`. La requête **sans** `search`, `official`, ville ou thème permet une recherche ouverte à toutes les communes et catégories. Source : https://developers.openagenda.com/agendas/recherche/

Cette route peut explorer des agendas **absents du backlog** OpenDataSoft et des 16 UID privés historiques. C'est plus large que le préflight `ptitesondes_dynamic_oa_agenda_discovery.py`, qui part uniquement d'événements ODS déjà détectés.

## Contrat technique

Fichier : `scripts/ptitesondes_openagenda_public_agenda_index.py`

- Requêtes GET seulement, origine HTTPS de l'API fixée, aucun suivi des redirections.
- Clé `oa_pk_` publique de lecture, dans l'en-tête HTTP, jamais dans l'URL ou les logs.
- 40 fiches maximum par page, 4 pages maximum par exécution, donc **160 UID au maximum** par exécution.
- Tous les agendas remontés sont inspectés sans filtrage par commune, titre, type d'activité ou champ `official` auto-déclaré.
- Vérifie chaque UID, slug et titre ; rejette les doublons dans le lot, la répétition de cursors et les réponses tronquées ou incohérentes.
- Les agendas déjà configurés sont comptés mais ne sont pas ajoutés comme nouvelles sources.
- Sauvegarde un **rapport privé** des nouveaux agendas candidats et un **curseur privé** pour reprendre le balayage à l'exécution suivante ; en fin de pagination, un nouveau cycle pourra commencer.
- Exécution explicite `--execute-live` uniquement ; par défaut, mode test sans réseau. Les dossiers privés sont en permissions 0700 ; fichiers créés en 0600 ; le rapport doit être nouveau.
- La sortie standard ne contient ni noms d'agendas ni UID ; aucun artifact public ni journal public détaillé n'est autorisé.

## Exemples conceptuels d'exécution privée

Ces chemins ne sont pas des fichiers présents sur GitHub. Ils doivent être fournis par un environnement **privé** qui possède le fichier `automation/sources.json` (configuration existante) et la clé publique `OPENAGENDA_READ_KEY`.

```bash
python scripts/ptitesondes_openagenda_public_agenda_index.py \
  --private-source-config /espace-prive/automation/sources.json \
  --private-cursor-state /espace-prive/cursors/oa-national.json \
  --output-private-report /espace-prive/reports/oa-page-001.json
```

La même commande avec `--execute-live` effectue effectivement les requêtes GET. Chaque exécution doit utiliser un **nouveau** chemin de rapport, tout en réutilisant le même fichier de curseur. Aucun planificateur n'est activé par cette PR.

## Ce que cela ne prouve PAS

L'index OpenAgenda ne certifie **ni** la légitimité d'un propriétaire d'agenda, **ni** l'organisateur d'une représentation, **ni** les droits de réutilisation, **ni** le lieu, **ni** les horaires, **ni** le public des séances. Un champ `official` ou un domaine d'URL auto-déclaré ne constitue pas une attestation indépendante.

Le futur raccordement doit procéder : **nouvel agenda indexé → identification de la vraie source → recherche de représentations → filtrage éditorial P'tites Ondes (musique, contes, spectacles jeunesse) → preuve du lieu y compris sans numéro → validation indépendante des séances → contrôle de doublons → publication conditionnelle.**

Ce chantier ne publie aucune séance. Les événements génériques (goûters, sports, randonnées et loisirs sans rapport radio/conte/spectacle) ne deviennent pas admissibles au seul motif de figurer dans un agenda nouveau.

## Points bloquants pour l'autonomie

1. Brancher les exécutions par lot à un planificateur **privé**, avec verrouillage des accès simultanés au curseur et rattrapage des échecs. Aucune modification de cron ici.
2. Parcourir régulièrement les événements des nouveaux agendas retenus, sans dépendre d'une sélection fixe.
3. Qualifier leur provenance institutionnelle, leurs séances et leurs lieux, sans assouplir les preuves d'accès public et de droits.
4. Contrôler le rendement réel : UID vus, agendas inconnus, provenance vérifiée, sorties valides, fiches publiées, répartition par territoire.

## Confidentialité et production

Aucune fusion, aucune publication, aucun workflow planifié ni écriture du catalogue. Toute donnée de découverte susceptible de contenir des intitulés doit rester dans les rapports privés. Cette PR est destinée à une revue isolée et à des tests sans réseau.
