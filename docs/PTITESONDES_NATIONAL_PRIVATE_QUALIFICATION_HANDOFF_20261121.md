# P'tites Ondes — raccordement national privé à la qualification existante

**21 novembre 2026 — prototype isolé, aucune fusion ni publication**

## Objectif

Relier les segments d'événements issus de la campagne privée nationale (#554) au **format du backlog** déjà utilisé par `Sarogal/PtitesOndes/automation/outings_intake.py`, sans construire un second éditeur, sans écrire le backlog réel et sans contourner le vérificateur indépendant. Ce module est la première étape du raccordement ; **ce n'est pas** la qualification ni la publication.

## Nouveau composant

`scripts/ptitesondes_private_national_qualification_handoff.py`

Entrées (chemins privés, hors dépôt public) :
- Rapport d'index national #547.
- Segment de recherche #554 produit par #553.
- Date exacte de la campagne.
- Clé **publique de lecture** OpenAgenda dans `OPENAGENDA_READ_KEY` lorsque `--execute-live` est demandé.

Garanties :
- Vérification du SHA-256 de l'index, du jour et de l'identité agenda / segment.
- Aucune confiance aveugle dans le titre, le lieu ou la date du premier balayage : chaque événement est relu sur l'API directe OpenAgenda v2, à UID d'agenda/événement fixé.
- Catégorie recalculée via le classificateur existant ; les événements étrangers, annulés, reprogrammés, éditorialement modifiés ou dépourvus de source canonique sûre restent en recherche.
- Seules les journées explicitement encore présentes dans l'ancien **et** le nouveau relevé sont proposées, les autres sont signalées pour une nouvelle exploration (aucune séance inventée).
- Place publique ou rue sans numéro acceptée **comme piste**, sans numéro, adresse ni GPS inventés.
- Jusqu'à **12 événements relus par invocation**, paramètre `--offset` pour poursuivre sans demander les UID manuellement. Ce plafond borne le réseau, pas les séances ni les événements admissibles.
- Le fichier privé de sortie contient deux ensembles : `backlog_leads`, au format exact du backlog privé historique, et `research_holds`, avec raisons de reprise.
- Tous les événements restent non approuvés. Aucune preuve d'organisateur, de droits, d'accès public, de géolocalisation indépendante ou de doublon n'est accordée.

## Commande de prévisualisation

Exemple de **lecture seule sans réseau et sans écriture** :

```bash
python scripts/ptitesondes_private_national_qualification_handoff.py \
  --private-agenda-index-report /espace-prive/index.json \
  --private-segment-report /espace-prive/segments/agenda-0000-segment-0000.json \
  --private-output-report /espace-prive/handoff/lot-0000.json \
  --day 2026-11-21
```

L'option `--execute-live` réalise jusqu'à 12 consultations publiques et enregistre **uniquement le rapport privé isolé** ; le moteur ne modifie aucun backlog existant. Pour lire les autres événements du même segment, on reprend au `next_offset` avec un autre fichier de sortie.

La sortie standard contient uniquement des nombres et des raisons fixes, sans UID, titre, lieu, URL, chemin privé ni clé.

## Rotation automatique sur les segments privés (sans cron)

Nouveau composant : `scripts/ptitesondes_private_national_handoff_rotation.py`.

Il découvre les fichiers `agenda-XXXX-segment-XXXX.json` déjà créés par la
campagne privée #554, puis appelle automatiquement le raccordement #563 pour
chaque lot de 12 événements, sans avoir à indiquer un index ou un offset.

- **Un checkpoint privé** suit `next_segment_index` et `next_offset`.
- Les segments sont parcourus dans l'ordre, sans trous silencieux. Les nouveaux
  segments ajoutés après une exécution terminée sont pris en charge à la
  prochaine invocation.
- Le verrou exclusif empêche les exécutions concurrentes ; un rapport écrit
  avant une interruption est récupéré seulement si son empreinte SHA-256,
  son identité de segment et son offset correspondent exactement.
- Le premier lancement et les relances ordinaires restent **sans réseau ni
  écriture** tant que `--execute-live` n'est pas présent.
- En mode explicite, jusqu'à 8 lots de 12 événements sont interrogés et
  écrits dans le **dossier privé**, jamais dans le catalogue ni dans le
  backlog actif. Les limites bornent une invocation et **ne sont pas** des
  plafonds éditoriaux ou des refus de séances.

Exemple :

```bash
python scripts/ptitesondes_private_national_handoff_rotation.py \
  --private-agenda-index-report /espace-prive/index.json \
  --private-campaign-segments /espace-prive/campagne/segments \
  --private-output-dir /espace-prive/campagne/handoffs \
  --day 2026-11-21
```

Après examen de la configuration de sécurité dans le runner privé, ajouter
`--execute-live` pour lire les événements et écrire les rapports privés.
Aucun calendrier de lancement n'a été ajouté.

**Adresses canoniques OpenAgenda :** une URL canonique externe est parfois
celle du site de l'organisateur. Elle ne bloque pas la découverte si la
réponse directe fournit un `slug` utilisable : le module reconstitue
l'adresse OpenAgenda exacte à partir de l'UID, du slug d'agenda et du slug
d'événement. L'URL externe n'est jamais prise pour une preuve d'organisateur.

## Étapes de raccordement encore à développer et à valider

1. Relier l'orchestrateur privé déjà développé à un runner planifié **après validation indépendante** de ses tests et de son stockage ; les nouveaux segments et offsets sont déjà repris automatiquement dans le code isolé.
2. Rejouer les lignes `backlog_leads` dans le **reconciler privé existant**, avec comparaison au backlog et au catalogue public, sans les injecter directement dans un patch.
3. Faire passer ces pistes dans la preuve directe des séances, l'organisateur indépendant, la géolocalisation et la vérification des catégories ; conserver les refus motivés, sans liste exhaustive de salles/agendas.
4. Adapter et tester le contrat de publication des lectures/spectacles de jeunesse dans `merge_policy.py` tout en préservant les fiches historiques.
5. Mesurer les vrais compteurs, y compris Corse et outre-mer, avant toute activation planifiée.

**Sécurité et autorisations :** aucun nouveau cron, aucune écriture du dépôt privé ou public, aucun secret transféré ni configuration de production modifiée par cette PR. Les PR restent en brouillon jusqu'à autorisation explicite.
