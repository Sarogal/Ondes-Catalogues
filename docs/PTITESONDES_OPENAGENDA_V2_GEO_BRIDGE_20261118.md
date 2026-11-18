# P'tites Ondes — preuve géographique indépendante réutilisable (18 novembre 2026)

**PR isolée / lecture seule / aucune publication.** Base : le code OpenAgenda API v2 de la PR #371, fusionnée par une autre intervention le 18 novembre. Ce nouveau lot ne fait pas partie de cette fusion. Ni Infomaniak, ni Grosses Ondes, ni le publisher, ni la configuration des runners privés ne sont modifiés.

## Pourquoi

Le funnel national du 18 novembre comportait environ 180 pistes bloquées au premier filtre par une géolocalisation non homologuée. La vague GPS statique #358 a déjà intégré quatre lieux à partir d'une adresse municipale et d'IGN/BAN, mais ne peut pas être recodée lieu par lieu à l'échelle nationale.

Ce module constitue **un vérificateur générique**, pas un homologueur automatique de sources. Une vérification structurelle seule ne prouve pas l'identité officielle du propriétaire du site ou le droit de republier l'événement.

## Contrat sans réseau

Le module scripts/ptitesondes_openagenda_v2_geo_bridge.py compare trois domaines de preuves :

1. Une **page de lieu institutionnelle** HTTPS épinglée dans un registre indépendant de la piste OpenAgenda, fournie par un appelant de confiance (adresse exacte et hôte exact, sans redirection). Son JSON-LD Place, Library, Museum ou type équivalent doit mentionner le nom du lieu et son adresse postale complète (numéro, voie, code postal, commune, France). Les alias ne sont admis que lorsqu'ils figurent dans la page du lieu.
2. Un **géocodage IGN/BAN** correspondant *exactement à cette adresse institutionnelle*, via https://data.geopf.fr/geocodage/search et une FeatureCollection valide. Il faut une entrée au numéro (type housenumber), un score au moins égal à 0,90, ville, voie, numéro, code postal et code INSEE syntaxiquement cohérents. Deux coordonnées contradictoires au même numéro rendent le cas ambigu.
3. L'emplacement OpenAgenda de l'événement : nom du lieu, commune, pays/territoire français et distance au résultat BAN **au plus 65 mètres**. Le jeu de coordonnées OpenAgenda n'est jamais utilisé seul comme géocodage de confiance.

En cas de convergence, le module renvoie un **point vérifié uniquement pour le diagnostic** sous forme compatible avec le contrôleur de structure OpenAgenda v2. L'adaptateur review_direct_with_independent_geo() enchaîne alors la revue directe sans produire d'événement ou patch. Il masque les noms, URL, UID, coordonnées et clés dans son rapport de sortie.

Des pages institutionnelles dépourvues de JSON-LD de lieu, des réponses BAN imprécises au niveau rue, les homonymies, les DOM non correctement documentés et les adresses litigieuses restent en attente. Le module ne synthétise pas de GPS.

## Conditions de sécurité pour le futur raccordement

- Le couple (approved_host, exact_url) doit provenir d'un **registre de confiance indépendant**, jamais d'un booléen approved du backlog, d'une URL déclarée dans OpenAgenda ou d'un site arbitraire découvert.
- Le récupérateur HTTPS de pages et le client IGN/BAN doivent contrôler l'URL finale, l'absence de redirection et la taille avant de transmettre le HTML/JSON au module. Ce module pur n'effectue pas ces connexions et ne peut pas s'en porter garant.
- La page de l'organisateur confirmant la date et l'heure, l'identité de l'agenda, la licence et son concédant, l'accès/âge, la catégorie et l'anti-doublon historique demeurent des vérifications **séparées et obligatoires**.
- Aucune preuve ne doit être réputée indépendante si elle provient d'un miroir ou d'une copie d'une même origine.
- Aucun mode de publication, de création de patch, d'autorisations GitHub supplémentaires ou de cron n'est inclus.

## Validation

La suite tests/test_ptitesondes_openagenda_v2_geo_bridge.py comprend 13 tests hors réseau (France métropolitaine, discordances ultramarines, JSON-LD falsifié/ambigu, hôtes trompeurs, mauvaise adresse, score faible, géométries contradictoires, hors rayon, alias non documentés, faux drapeaux d'approbation, composition avec la preuve API). Ces tests utilisent uniquement des données synthétiques.

**Étapes restantes :** adapter génériquement les pages institutionnelles réelles sans schéma JSON-LD, vérifier la provenance des pages récupérées, mettre en cache et faire tourner les géocodages exacts du backlog en lecture seule, mesurer le nombre de lieux réellement débloqués, puis relier la revue complète au publisher après validation. Aucune nouvelle fiche n'est revendiquée par ce lot.

## Récupération bornée et exécution par lot (suite du 18 novembre)

L'adaptateur accepte désormais un `Place` explicitement typé dans le champ `location` d'un `Event` JSON-LD institutionnel. Ce contrat est **générique** : aucune exception par salle ou représentation. Plusieurs événements décrivant exactement le même bâtiment sont rapprochés par adresse réelle ; leurs alias explicitement présents peuvent être réunis. Deux adresses ou numéros contradictoires restent bloquants. Le parcours JSON-LD est borné et non récursif.

Deux modules complémentaires, toujours **déconnectés de la production**, préparent le traitement réel :

- `scripts/ptitesondes_openagenda_v2_geo_fetch.py` : récupère uniquement une page HTTPS déjà épinglée par un registre externe de confiance (statut 200, URL finale identique, pas de redirection, contenu HTML borné), puis construit depuis son adresse exacte une requête IGN/BAN au numéro, avec réponse GeoJSON bornée. Aucun secret ni URL OpenAgenda fourni comme source de confiance.
- `scripts/ptitesondes_openagenda_v2_geo_batch.py` : vérifie au maximum **60 pistes par lot**, en mémorisant les réponses sur la seule durée d'un lot pour un document institutionnel identique et une adresse IGN/BAN identique. Chaque fiche reste néanmoins revérifiée séparément pour son identité, ses coordonnées, dates, fuseau, statut et indices du public. Le rapport de sortie contient seulement des compteurs à nomenclature fixe, jamais de titre, URL, UID, âge, lieu, coordonnées ou détail d'erreur privée.

Les caches ne donnent **aucun** droit d'approbation et ne transforment pas deux miroirs d'un même UID en deux sources indépendantes. Le module ne détermine pas lui-même si un domaine appartient réellement à la collectivité : cette identité doit provenir du registre des sources homologuées, jamais d'un booléen ajouté au backlog ou d'une annonce OpenAgenda. Aucune mise à jour de registre, pipeline, catégorie, entrée de catalogue, secret, cron ou publisher n'est prévue dans cette PR.

Deux séries de tests purement simulés contrôlent les refus de transport, les conflits d'adresse, les ambiguïtés JSON-LD, les réutilisations de cache et la confidentialité. Une réussite CI atteste seulement ces comportements hors réseau : aucune couverture de lieu ou de sortie supplémentaire n'est revendiquée sans contrôle réel de données sur un environnement de confiance.

### Prochaine intégration nécessaire

1. Homologuer les hôtes/pages institutionnels par une source indépendante réutilisable, et construire un registre **sans autorisations automatiques fondées sur OpenAgenda seul**.
2. Alimenter les lots de diagnostic avec les pistes du backlog privé ; quantifier combien des premiers refus GPS deviennent des preuves de localisation à trois sources, en conservant les échecs et taux de troncature.
3. Vérifier ensuite les autres critères indépendants, notamment organisateur, droit de réutilisation, âge/accès, catégorie, dates locales, doublons historiques et publication réelle. Une preuve géographique seule ne peut jamais publier.
