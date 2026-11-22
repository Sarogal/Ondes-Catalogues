# P'tites Ondes — exploration nationale des événements des nouveaux agendas

**21 novembre 2026 — PR de prévisualisation privée, sans publication**

## Chaîne de recherche

1. Le scanner national de #547 parcourt les **agendas publics indexés**, sans filtre de ville, de lieu ou de thème, et produit une file de **sources candidates**.
2. `ptitesondes_openagenda_national_event_research.py` peut sélectionner un agenda de cette file, vérifier son identifiant UID et son slug directement auprès de l'API, puis lire ses événements publics.
3. La route officiellement documentée est `GET https://api.openagenda.com/v2/agendas/{agendaUID}/events`. Les paramètres `relative[]=current&relative[]=upcoming` limitent aux programmes en cours ou futurs. La pagination reprend le tableau de **chaînes** `after[]` fourni par le service, sans transformer les nombres à zéros initiaux en entiers.
4. Chaque événement est examiné **sans liste de lieux connus**. Le moteur recherche les indices éditoriaux autorisés : concerts, éveil musical, ateliers sonores, comptines, contes/lectures d'histoires et spectacles jeune public, à destination des enfants.
5. Un « goûter au parc », un cours de sport, une balade nature, une visite de ferme ou un atelier de poterie **sans contenu pertinent** ne passe pas cette proposition éditoriale. Un événement mal catégorisé ou avec un intitulé d'œuvre peu explicite peut néanmoins nécessiter une recherche supplémentaire : l'absence d'indice dans l'extrait ne constitue pas une preuve qu'il est hors périmètre.
6. Un lieu inconnu et une place **sans numéro de rue** restent des pistes : la **preuve géographique indépendante** est une phase séparée (#541/#548), jamais une condition de découverte initiale.
7. Des séances multiples le même jour ne sont pas plafonnées arbitrairement. Les dates sont tirées exclusivement des horaires explicites et doivent encore être revérifiées lors de la qualification.

Documentation API : https://developers.openagenda.com/10-lecture/ ; index des agendas : https://developers.openagenda.com/agendas/recherche/

## Portée technique de ce lot

- Lecture seule, exclusivement en GET, domaine HTTPS de l'API fixé, pas de redirection, clé publique `oa_pk_` placée dans l'en-tête plutôt que dans l'URL.
- **Un agenda par exécution**, 20 événements/page et 3 pages au maximum, soit 60 événements analysés par invocation. Si le dernier segment contient un curseur, le prochain passage peut reprendre ce même agenda.
- Entrée : rapport privé produit par le scanner #547, contenant les sources **candidates**, pas des sources approuvées.
- Identification à nouveau du couple UID/slug directement sur OpenAgenda avant la lecture d'événements.
- Écriture d'un rapport privé détaillant les propositions, les dates vues, les lieux et communes à vérifier, les compteurs de motifs et le curseur de reprise.
- L'état de reprise contient l'UID d'agenda et l'empreinte SHA-256 exacte du fichier d'index : il ne peut être réutilisé par erreur pour un autre lot ou un autre agenda.
- Par défaut **aucun réseau ni écriture** ; les GET demandent explicitement `--execute-live`.
- Aucun événement n'est admis, aucune licence ni preuve organisateur n'est présumée, aucune donnée n'est envoyée au catalogue ou au moteur public de publication.

## Exécution dans un espace privé

Le script doit être invoqué depuis une copie de code qui peut lire le rapport privé de #547, mais **ne doit pas placer ce rapport dans le dépôt public**, dans un artifact Actions public ou dans des logs.

```bash
python scripts/ptitesondes_openagenda_national_event_research.py \
  --private-agenda-index-report /espace-prive/rapports/index-001.json \
  --candidate-index 0 \
  --private-cursor-state /espace-prive/etat/agenda-0.json \
  --output-private-report /espace-prive/rapports/evenements-001.json \
  --day 2026-11-21
```

Ajouter `--execute-live` pour effectuer la lecture avec `OPENAGENDA_READ_KEY`, clé publique de lecture en environnement privé. Le fichier de rapport doit être nouveau à chaque passage. Le dossier privé doit être en permissions 0700 et les rapports sont en 0600.

## Non couvert : ce qu'il reste à industrialiser

- **Planification privée** : balayer automatiquement les candidats d'index, traiter tous les agendas et leurs pages avec des curseurs séparés, relancer sans collision ni doublon et maintenir un historique de recherches.
- **Enrichissement et confiance** : retrouver les descriptions des œuvres peu explicites, les représentations et leurs organisateurs officiels, la licence, le public et les conditions d'accès.
- **Geocodage des lieux** : recouper les lieux inconnus, rues non numérotées et points dans des espaces publics avec des sources indépendantes. Ne jamais inventer de coordonnées.
- **Passerelle de publication** : ne lier ces pistes qu'après vérification des séances et contrôle des doublons, adaptation des catégories contes/spectacles au schéma public, et revue complète.
- **Validation opérationnelle** : exécution réelle depuis un runner privé autorisé, comptages de nouvelles pistes et fiches fiables par région, couverture de la Corse et des territoires ultramarins.

L'index API peut comprendre des agendas hors de France ; les indications de pays trouvées sur les événements restent donc elles-mêmes des **pistes non attestées**. Le pipeline de qualification doit confirmer le territoire.

**Aucune fusion, aucun cron, aucune modification du site ou du catalogue, aucune preuve de collecte live à cette étape.**
