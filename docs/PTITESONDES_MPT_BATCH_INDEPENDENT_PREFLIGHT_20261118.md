# P'tites Ondes — contrôle indépendant multi-événements depuis l'agenda MPT

**18 novembre 2026 — PR empilée, brouillon, 0 admission, 0 publication.**

## Objectif

Passer d'une unique séance de démonstration à **un lot variable de pages et de séances réelles**, sans écrire un vérificateur à chaque événement. Les règles de preuve sont génériques pour **toute fiche municipale du format étudié**. L'identité GPS de chaque bâtiment reste fournie par un registre indépendant, jamais par une suggestion du collecteur.

**Dépendances non fusionnées :**
- **#360** : découverte bornée des fiches officielles des [Maisons pour tous de Montpellier](https://mpt.montpellier.fr/evenements) et extraction des séances familiales ;
- **#361** : trois premiers bâtiments dont les adresses municipales ont été recoupées avec les données géographiques IGN ;
- **#362** : contrôle strict premier article officiel, date et heure dans le même bloc visible, prévalidateur indépendant national.

Cette branche est **empilée sur #362**. Pour tester la composition sans fusionner #360, elle réutilise *exactement* ses modules de découverte, d'adaptation des pages et de tests : il faudra **rebaser/réconcilier ces fichiers** si #360 est intégrée avant cette PR. Il ne s'agit pas d'un nouveau moteur concurrent.

## Registre géographique indépendant : 7 bâtiments

Les trois lieux initiaux de #361 restent inchangés. Quatre autres sont retenus à partir de fiches municipales effectivement relues et de réponses IGN au **numéro de voie**, obtenues le 18/11/2026 :

| Lieu | Source municipale de l'adresse | Adresse exacte vérifiée par IGN | Coordonnées (latitude, longitude) | IGN |
|---|---|---|---|---|
| MPT Michel Colucci | [Atelier cuisine](https://mpt.montpellier.fr/evenement/drole-de-zebulon-atelier-de-cuisine) | 205 rue de Cheng-Du, 34070 Montpellier | 43.593964, 3.840626 | housenumber, 0.9732 |
| MPT Marie Curie | [Le corps ! Le jeu !](https://mpt.montpellier.fr/evenement/le-corps-le-jeu-atelier-de-motricite) | 13 allée Antonin Chauliac, 34080 Montpellier | 43.612888, 3.830471 | housenumber, 0.9769 |
| MPT L'Escoutaïre | [LAEP](https://mpt.montpellier.fr/evenement/rendez-vous-au-lieu-daccueil-enfants-parents-laep) | 67 rue des Razeteurs, 34070 Montpellier | 43.595533, 3.884113 | housenumber, 0.9704 |
| MPT François Villon | [Spectacle de cirque](https://mpt.montpellier.fr/evenement/attention-ta-tete-spectacle-de-cirque-jonglage-antipodisme-danse) | 55 rue des Araucarias, 34080 Montpellier | 43.615165, 3.839472 | housenumber, 0.9725 |

Les géocodages indépendants sont obtenus au moyen des requêtes `https://data.geopf.fr/geocodage/search` épinglées dans le fichier de registre. Le test live les relit et exige **une seule correspondance** (`housenumber`, score ≥ 0.95, distance ≤ 15 m, ville/code postal/adresse concordants). Il ne suffit pas d'avoir un résultat géographique dans la commune.

**Deux contre-exemples maintenus en attente** :
- *Médiathèque Victor Hugo*, 207 rue Guillaume Janvier : la page municipale donne le code postal 34000 tandis que le géocodeur renvoie 34070 avec score ~0.808, **non retenu** ;
- *MPT Albert Camus*, allée Maurice Bonafos : géocodage au niveau de la rue, **non retenu**.

## Prévalidation automatique de lot

`scripts/ptitesondes_mpt_batch_independent_review.py` :
1. Lit la liste officielle et **au plus 24 fiches détaillées** (`ptitesondes_mpt_listing_discovery.py`) ;
2. extrait les séances explicitement datées, avec le filtre de public enfant (aucune expansion de périodes vagues ou d'invitations privées) ;
3. utilise les fiches officielles déjà relues **sans renvoyer une deuxième requête pour la même URL** ;
4. soumet les séances à `independent_family_preview` — géocodage IGN indépendant, concordance titre, lieu, adresse, séance et conditions d'accès, puis prévalidation nationale #346 et anti-doublons ;
5. refuse un échantillon dont une page a échoué, et **compte** les séances qui dépassent la limite de 24 sans les faire passer silencieusement ;
6. retourne uniquement des **compteurs anonymes**, aucun titre, URL, HTML ou preuve utilisable comme entrée directe du publieur.

La limite de 24 fiches constitue **un échantillon, pas la couverture totale** de Montpellier ou d'autres villes. Ce moteur n'est **pas encore connecté à la veille programmée**. Un passage géographique réussi ne signifie pas que le spectacle est ouvert au public ou accepté par un organisateur.

## Règles éditoriales conservées

- « Méli’Pitchouns » : `Gratuit` avec carte MPT obligatoire, donc **prix/conditions ambigus** tant que l'obligation n'est pas examinée ;
- « Dans la forêt » : installation d'art en intérieur, **pas une sortie nature** déduite automatiquement du titre ;
- « Bébés lecteurs » : la médiathèque Émile Zola peut être l'organisateur, la MPT Frida Kahlo est le **lieu** ;
- les événements scolaires / réservés aux crèches et les séances historiques expirées ne sont jamais admis comme sorties familiales ordinaires.

## Sécurité et livraison

- Aucune écriture sur `docs/ptitesondes/sorties.json`, `lieux.json`, les secrets, les scripts de publisher, les branches de production, les dépôts privés ni Infomaniak ;
- workflow GitHub Actions **public**, droits `contents: read`, pas de cron, pas de secret ;
- audit d'abord **hors réseau** avec plusieurs fiches synthétiques, cas de page manquante, réponse géo dégradée, dépassement de quota et rapport anonymisé, puis **une lecture réelle ponctuelle** de l'agenda officiel et de l'IGN sous PR ;
- résultat du prévalidateur = **indices de source indépendants**, pas preuve de l'identité du producteur, pas approbation privée, pas publication.

### Suite après validation

Mesurer les refus réels par raison, enrichir progressivement le **registre indépendant des lieux récurrents** à partir des adresses municipales fiables, puis concevoir un dossier de décision privée (organisateur, conditions, droits, anti-doublons) et seulement ensuite proposer un raccordement au publisher. Ne **jamais** assouplir les contrôles pour faire monter artificiellement le compteur.

**Cette PR ne doit pas être fusionnée sans autorisation.**
