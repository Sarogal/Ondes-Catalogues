# P'tites Ondes — découverte en lot des Maisons pour tous de Montpellier

**17 novembre 2026 — brouillon sans publication ni nouvelle programmation cron.**

## Problème résolu sur branche isolée

Le premier adaptateur national #350 savait lire une fiche MPT (« Parcours motricité »), mais n'explorait pas les autres fiches de l'agenda. Cela limitait artificiellement la couverture à une page, même si la source officielle en propose beaucoup.

## Source primaire

- [Agenda municipal des Maisons pour tous](https://mpt.montpellier.fr/evenements)
- Exemple officiel : [Parcours motricité](https://mpt.montpellier.fr/evenement/parcours-motricite)
- Autres programmes effectivement présents sur l'agenda : « Méli'Pitchouns », « Bébés lecteurs », « Dans la forêt », « Cocon paisible » et des ateliers parents-enfants. **Leur présence n'est pas une preuve de session publiable.**

Le moteur énumère des liens de fiches municipaux strictement autorisés sur `mpt.montpellier.fr/evenement/`, supprime les doublons, vérifie les pages détail séparément et conserve seulement les occurrences explicitement datées pour les familles.

### Bornes et critères

- Source HTTPS précise, hôte strict `mpt.montpellier.fr`, sans utilisateur, port personnalisé, query ni fragment.
- Le collecteur ne traite pas les pages autres que celles explicitement liées depuis `https://mpt.montpellier.fr/evenements`.
- Maximum 80 liens détectés, échantillon **24 pages détaillées maximum** dans le smoke CI, soit les 24 liens détectés dans la première lecture réelle ; ce seuil reste plafonné et ne garantit pas l'exhaustivité des agendas de la ville.
- Taille de chaque page <= 1,5 Mio, délai HTTP 12 s, pas de redirection, petite temporisation entre lectures.
- Une page inaccessible est décomptée **en attente**, jamais comme une absence de programme.
- Les journées futures sont lues sans deviner une récurrence, et sans inventer âges, lieux ou données GPS.
- La mention « gratuit » accompagnée d'une carte MPT obligatoire demeure **ambiguë**, pas transformée en accès libre inconditionnel.
- Les activités adultes ne sont pas converties en fiches familiales sur le seul nom du lieu.
- Les flux de pages historiques `/index.php/evenement/` ne sont **pas** automatiquement réécrits en liens /evenement/ supposés équivalents ; ils nécessitent une homologation ultérieure.

## Séparation de responsabilité

- Script sans réseau `ptitesondes_mpt_listing_discovery.py` : détecte les liens, accepte une lecture détail injectée, transmet en mémoire des **pistes**, et produit un rapport public **anonyme**.
- Script one-shot `ptitesondes_mpt_listing_live_smoke.py` : lit une liste et maximum 24 pages, ne persiste aucun candidat.
- Aucune écriture dans les catalogues, aucun secret GitHub, aucun appel au publisher, aucune transmission vers la branche privée, aucune modification des workflows programmés.
- Les étapes de prévalidation #342/#346, du contrôle de provenance GPS, de la qualification d'âge/public, de l'approbation privée et de la publication restent **distinctes et obligatoires**.

## Tests et activation

`tests/test_ptitesondes_mpt_listing_discovery.py` couvre les domaines spoofés, les liens cachés, les pages adultes, l'absence de détails, le plafond de pages et l'absence de publication.

CI dédiée sur runner public, lecture seule, déclenchée sur la PR. Le premier smoke de 12 pages a détecté **24 liens municipaux**, lu **12 fiches**, trouvé **5 occurrences familiales structurées**, sans aucune erreur réseau. Le nouvel échantillonnage jusqu'à 24 fiches vise à mesurer les pistes des autres pages, sans créer d'événements ni présumer de l'approbation privée. L'ajout d'un cron et le transfert privé exigeraient un lot supplémentaire audité et une validation explicite.

**Ne pas fusionner ni déployer sans accord explicite.**
