# P’tites Ondes — découverte générique depuis un index HTML officiel

**19 novembre 2026 — PR en brouillon, mode lecture seule, aucune activation.**

## Motivation : ne pas réduire la veille aux seuls agendas OpenAgenda

La PR #416 peut découvrir des racines OpenAgenda depuis les pages
institutionnelles. Mais une grande partie des organismes publie une liste
HTML de fiches événements sur son **propre domaine**, parfois sans agenda
OpenAgenda.

Vérification externe, le 19 novembre : la page institutionnelle
`https://mpt.montpellier.fr/evenements` est accessible, et son inventaire
de liens publics contient **24 URL distinctes** au format
`https://mpt.montpellier.fr/evenement/<slug>` (observation en lecture seule
avec extraction des liens ; **pas** une qualification du contenu de ces
24 pages, ni une exécution de l'adaptateur proposé).

Ce n'est pas un motif pour coder vingt-quatre exceptions événement :
un **extracteur d'index HTML réutilisable** suffit à nommer leurs pages
pour une vérification indépendante ultérieure.

## Contrat technique

`scripts/ptitesondes_official_html_index_discovery.py` reçoit :
- un index approuvé **indépendamment** de chaque candidat :
  `approved_host`, `exact_index_url` ;
- le HTML récupéré par GET à cette URL **exacte**, HTTPS, redirections
  interdites, réponse de taille et type bornés par le transport déjà existant.

Son lecteur HTML :
- ne retient que les liens **visibles à l'intérieur de `<main>`** ;
- exclut `header`, `footer`, `nav`, scripts et fragments cachés ;
- n'autorise que les URL relatives ou HTTPS menant au **même hôte exact** ;
- bloque les faux domaines, identifiants d'URL, fragments, query strings,
  URLs `javascript:`, `mailto:` et cibles inconnues ;
- conserve deux URL distinctes même lorsqu'elles portent le même titre :
  les séances multiples ne doivent pas être fusionnées par le seul libellé ;
- refuse tout document ou nombre de propositions dépassant ses bornes.

Les propositions sont **privées**, fournissent uniquement une URL d'étape
suivante avec un libellé d'index en indice, et portent
`status=requires_exact_child_fetch_and_independent_event_proof`,
`approved=False`.

### Sorties publiques autorisées

La fonction `redacted_html_index_counts` n'expose que quatre compteurs
avec des clés fixes : liens d'index, pages enfants du même hôte, liens hors
périmètre, doublons. Elle retire toutes les URL, UID, villes, titres,
marqueurs de catalogue, coordonnées et réponses HTML.

**Aucune piste n'est admise comme sortie**. Une URL ne prouve pas une
date, une séance, une identité d'organisateur, un lieu/GPS, un public
enfant, les droits de réutilisation ou une absence de doublon. La page
enfant devra être demandée par un lecteur privé puis passer les
vérificateurs existants (incluant l'âge, la source indépendante et les
droits). Une page HTML sans `main` ne produit pas de candidat : il faut
en revoir le contrat de contenu, pas élargir silencieusement la preuve.

## Tests et limites

La CI de PR teste les pages du type « index de ville → fiches » sur des
fixtures adversariales, sans requête HTTP réelle, avec contrôle des
redirections et de l'anonymisation.

Le composant est **hors chaîne de collecte, d'admission et de publication**.
Il ne programme aucune nouvelle exécution et ne crée aucun registre
institutionnel automatiquement. La priorité suivante est l'orchestrateur
privé capable de lire les pages d'index validées, de suivre les fiches
candidates puis de dresser un tableau des preuves manquantes **sur le
backlog réel**, sans journaliser les contenus sensibles publiquement.

Aucune modification de `docs/ptitesondes/sorties.json`, des lieux,
de GitHub Pages ou d'Infomaniak n'est autorisée par cette PR.
