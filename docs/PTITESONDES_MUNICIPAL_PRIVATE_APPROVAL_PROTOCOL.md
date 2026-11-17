# P’tites Ondes — protocole proposé d’approbation municipale privée

**Statut : conception à valider. Non actif. Pas d’autorisation de publication.**

## Principe de séparation des rôles

Le collecteur municipal, les producteurs de dossiers privés et les contrôleurs
de conditions d’accès ne peuvent jamais s'accorder eux-mêmes une approbation.

La PR #325 contient uniquement la **contre-vérification des preuves**.
Une future étape d'approbation ne pourra être activée qu'après validation
explicite et tests adversariaux de son identité.

## Identité et preuves gelées

Un dossier doit porter un identifiant stable
\`municipal-gosier-{spip_id}-{YYYY-MM-DD}\` et un manifeste privé décrivant :

- source officielle autorisée, identifiant municipal, titre exact, occurrence
  et horaire local, fuseau \`America/Guadeloupe\`, âge explicitement vérifié ;
- provenance du bâtiment exact et GPS documenté ; catégorie non musicale ;
- empreinte SHA-256 du dossier de qualification **et** du rapport d'accès ;
- date de vérification, source et empreinte du catalogue public pris en compte ;
- état exact du tarif et de l'inscription : explicites, absents ou contradictoires ;
- résultat des contrôles de doublons, séries, événements passés ou annulés.

Le rapport de prévalidation seul **ne contient jamais un droit d'écriture**.

## Accord éditorial humain

Proposition : utiliser une PR **privée distincte et limitée aux manifestes de
décision**, relue par une personne autorisée qui n'est pas le producteur
automatique du dossier. Le prévalidateur doit vérifier via l'API GitHub :

1. L'identité du reviewer et ses droits au dépôt privé (ne pas faire confiance
   à un nom écrit dans le JSON).
2. Un avis \`APPROVED\` non révoqué, rattaché au **head SHA exact** et au
   manifeste de preuves. Un changement de commit annule la validité.
3. Une décision explicite par occurrence (pas d'autorisation globale pour une
   série), avec catégorie, horaire, âge et éventuelle mention publique.
4. Les décisions sur prix/inscription **non précisés** : accepter explicitement
   la formulation « Voir conditions » et le renvoi à la fiche officielle,
   jamais « Gratuit » ou « Sans inscription » présumés.
5. L'absence de conditions contradictoires, de changement du site source ou de
   doublon au moment de la publication.

Un fichier \`approved: true\` ou une PR sans review authentifiée **ne suffisent pas**.

## Promotion contrôlée

La voie municipale devra rester distincte de la voie OpenAgenda :

- le public ne doit jamais recevoir les identités privées des relecteurs ni
  les rapports bruts ou jetons ;
- le synchroniseur doit recouper la preuve municipale avec le HTML officiel,
  l'identité du lieu, la catégorie et l'état récent du catalogue ;
- en cas d'écart, de 403/404, de changement d'heure, de complet, d'annulation
  ou de preuve vieillie : arrêt, retour en revue humaine ;
- le synchroniseur publie seulement **des ajouts** \`ptitesondes.patch.v1\`
  acceptés avec origine municipale explicitement documentée ;
- aucune suppression, correction historique, nouvelle planification dans le
  dépôt privé ou assouplissement silencieux des règles OpenAgenda.

## Mise en service par étapes (toutes soumises à approbation)

1. Terminer la compatibilité des 4 catégories avec la carte et le modèle public.
2. Vérifier le prévalidateur contre les 9 séances du Gosier sur runner public,
   avec rapports et preuves retournés exclusivement au dépôt privé.
3. Implémenter le contrôle de review GitHub et les tests anti-usurpation.
4. Ajouter le générateur municipal **après** preuve de review authentifiée,
   en mode simulation sans écriture.
5. Effectuer un dry-run du synchroniseur sur copie du catalogue, vérifier zéro
   modification des 548 fiches historiques existantes.
6. Faire valider séparément la fusion, le déploiement Infomaniak et chaque
   éventuelle première vague de publications.

CINOR conserve son origine OpenAgenda authentifiée et son circuit spécifique ;
la collecte métropolitaine et corse continue sans changement.
