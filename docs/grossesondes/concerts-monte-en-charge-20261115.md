# Grosses Ondes Concerts — montée en charge du registre privé

## Contrat inchangé (15 novembre 2026)
- Chaque concert nouvellement publié a une preuve nominative officielle et passe `concerts_cloud_sync.validate_approval`. Un guest inconnu n'est jamais un nouvel artiste.
- Les approbations privées sont conservées intégralement, dans leur ordre et sans modification rétrospective. Les événements publics existants correspondent exactement à ces signatures.
- La publication est limitée à **16 nouveaux concerts par synchronisation** (maximum de nouvelles salles inchangé). Ce garde-fou ne constitue pas un plafond d'artistes ou de concerts référencés **au total**.
- Aucun jeton, preuve privée, contenu d'approbation ou refus nominatif n'est exposé dans des journaux publics.
- Les exécutions programmées restent sur les runners PUBLICS. Aucune publication n'est activée par ce chantier.

## Étape technique préparée dans cette PR
- Suppression du plafond arbitraire de **400 approbations cumulées**. Le contrôle est désormais sur la validité et l'immutabilité de chaque enregistrement; les nouvelles publications restent bornées à 16 par passage.
- Le registre approchant ou dépassant 1 Mo devient inaccessible via l'encodage Base64 par défaut de l'API Contents. On récupère sa métadonnée SHA, puis son **blob privé exact par SHA**; l'accès conserve le même jeton lecture seule et vérifie SHA et taille. Ce mécanisme fonctionne aussi pour la prévalidation des PR privées.
- La limite de taille technique de 20 Mo protège les runners d'un contenu déraisonnable et ne constitue pas une limite sur le **nombre** de groupes ou de concerts. Elle devra être remplacée par un registre segmenté pour une grande archive.
- Tests sans réseau : réponse GitHub standard, seuil >1 Mo simulé, SHA divergent, taille falsifiée, erreur d'encodage, prévalidation privée et plus de 400 approbations.

## Projet de traitement FIFO par lots du 16 novembre 2026 — PR isolée
- Le synchroniseur prépare **au maximum 16 nouveaux événements** dans une transaction. Les approbations suivantes ne sont ni effacées ni classées comme refus : elles restent présentes dans le registre privé et sont reprises au cycle suivant.
- Les identifiants des événements déjà publiés dans le JSON cloud constituent le point de reprise durable. Le moteur recommence depuis les approbations append-only ; toute approbation déjà publiée est revérifiée contre les champs immuables.
- La protection contre les doublons d'identifiants dans le registre s'applique même au-delà de 400 lignes. Aucun événement différé ne contourne `validate_approval` ou les preuves officielles lorsque son tour arrive.
- La prévalidation privée simule les lots successifs **sans aucune écriture** lorsque la file contient déjà des approbations antérieures non publiées.
- **Limite importante :** les preuves expirées restent refusées lors de leur tour. Une longue attente exige une revérification officielle signée, sans prolonger artificiellement les dates.
- **Statut :** uniquement sur la branche expérimentale, non fusionnée. Aucun changement de calendrier d'exécution ni de production.

## Reprise des validations de salles — branche isolée du 16 novembre 2026
- Le plafond de **100 salles approuvées dans le registre privé** est supprimé. Tous les dossiers conservés sont indexés par identifiant ; les doublons d'ID et les dossiers incomplets restent refusés.
- Au maximum **six nouvelles salles par exécution** : les demandes restantes deviennent `deferredVenues`, sans supprimer d'approbations ni assimiler les salles différées à un refus.
- À chaque passage, les salles déjà publiées sont **revalidées** contre la preuve privée persistante ; les dossiers non encore publiés sont vérifiés lorsque leur tour arrive.
- Les concerts liés à une salle différée restent bloqués jusqu'à la vérification et la publication de cette salle : aucune latitude, longitude ou localisation de substitution n'est inventée.
- Couverture de test : 101 demandes, lots successifs de six jusqu'à épuisement, redémarrage idempotent, septième preuve invalide différée puis refusée, doublon de salle.
- La limite technique de **20 Mo** sur la taille du registre demeure ; prévoir sa segmentation avant de la rencontrer. **Aucune activation en production ni nouvelle approbation réelle.**

## Isolement des refus historiques dans la prévalidation privée
- Une approbation **ancienne, non publiée et devenue invalide** est conservée comme refus/attente ; elle ne doit pas paralyser la prévalidation d'une nouvelle date indépendante et correctement signée.
- Le prévalidateur ne tolère ce cas que si l'ID retenu appartient à un dossier `previous.approvals` **encore absent du catalogue public**. Un ID de nouvelle approbation, de salle ou de concert déjà publié en erreur fait **toujours échouer** la prévalidation.
- L'événement nouvellement approuvé doit effectivement apparaître dans le catalogue simulé, avec le bon ordre et les artistes signés ; le contrôle officiel individuel reste obligatoire.
- Simulation : 16 dates publiées, 17e preuve ancienne expirée, 18e date valide acceptée ; 18e preuve fausse toujours refusée. **Aucune approbation privée effective n'est créée.**

## Tableau de bord GitHub Actions — indicateurs agrégés
- Le résumé du workflow public affiche désormais, en proposition isolée, `deferredUnprocessed` (concerts conservés pour le prochain cycle), `deferredVenues` (salles conservées), `newVenues`, `alreadyRegisteredVenues`, les événements ajoutés et les retenues.
- Un simple **notice** GitHub signale une file non vide sans en publier le contenu, les URL de preuve ou les identités de dossiers non publiés.
- Le rapport détaillé et les refus privés restent uniquement dans le stockage éphémère du runner ; il n'est jamais attaché à une exécution publique.
- Ce changement concerne **uniquement le texte récapitulatif** du workflow. Ni calendrier, ni condition de publication, ni jeton, ni JSON public ne sont modifiés.

## Nouveau registre de salles approuvées par revue Git — étape préparatoire v1
- **Verrou découvert :** `validate_venue_approval` rejetait toute salle absente de `PILOT_VENUES`, une liste écrite à même le code du publisher. Ce point empêche la croissance nationale au fil des découvertes.
- La proposition ajoute `automation/concerts/reviewed_venue_specs_v1.json`, un registre **initialement vide**, à schéma strict. Aucun nouvel établissement réel n'est ajouté ou autorisé par défaut.
- Pour une salle absente de l'ancienne liste, **deux contrôles indépendants doivent converger** : (1) identité/adresse/GPS exacts dans ce fichier public versionné et *revu avant intégration sur main* ; (2) approbation privée indépendante avec première source officielle nom/adresse et deuxième source de géolocalisation nominative de type exact. Les dates de vérification et les champs sont exigés.
- Les anciennes fiches `PILOT_VENUES` sont conservées sans conversion ni assouplissement, y compris l'exception du MeM nécessitant une photo indépendante.
- Le registre refuse les doublons avec les salles historiques, les IDs incohérents, les champs inattendus, les URL non HTTPS et les coordonnées impossibles. Chaque changement de référence peut invalider une approbation privée et bloque alors la synchronisation : pas de réécriture silencieuse des salles déjà publiées.
- Le workflow public doit réagir aux changements de ce registre et interdire un rebase d'une publication calculée sur une version antérieure de ces références.
- **Limite de confiance :** cette v1 est une *porte de sortie du code source*, **pas** une autorisation automatique de nouvelles salles issues d'une seule source. Il faudra ensuite industrialiser l'alimentation du registre avec preuves effectivement revues et règles de protection de branche. Ne jamais auto-fusionner les propositions de salles sans ces garanties.
- Tests entièrement synthétiques : nouveau lieu sans entrée publique rejeté ; profil ajouté au registre + dossier signé accepté ; fausses adresses et fausses coordonnées rejetées ; registre tronqué/incohérent rejeté ; intégration du lieu dans un catalogue candidat isolé.
- Aucune modification du JSON de production ni des salles existantes.

## Étape suivante AVANT généralisation des gros lots
La file privée actuelle est un JSON cumulatif. Sur la **branche expérimentale**, l'éditeur traite au plus 16 approbations admissibles par passage et laisse les suivantes dans la file, sans les perdre ni les publier sans contrôle. La reprise est reconstruite depuis les identifiants d'événements effectivement publiés. Ce mécanisme n'est **pas encore fusionné** ; la limite de 16 publications par transaction reste obligatoire.

Plan d'intégration à tester dans une PR dédiée :
1. Construire une file **append-only** de lots d'approbations identifiés par empreinte (indices de début et de fin, SHA du lot et de la version du registre).
2. Prévalider chaque événement avec le véritable `validate_approval`, en tenant compte des artistes et salles publiés précédemment; ne jamais traiter une preuve documentaire comme un simple booléen de confiance.
3. Ne publier que **16 événements validés par transaction**, avec un curseur durable et idempotent et une empreinte de l'état de départ. Les refus sont conservés hors du lot; les événements valides passent sans être bloqués par un autre échec.
4. Interdire les conflits sur le même concert, la même URL ou le même artiste/salle/date entre deux lots; conserver les éventuelles dépendances d'artistes nouvellement approuvés.
5. En cas de crash, vérifier que le catalogue public représente **exactement** une étape précédente avant de reprendre; sinon interrompre. Garder l'historique et le rapport privé des refus.
6. Re-vérifier les approbations dont les sources sont trop anciennes pour la règle source; ne pas publier une pièce expirée par simple rattrapage.
7. Simuler 1 000, 5 000 et 20 000 fiches avec interruption, relance, doublons, faux artistes et changement de salle. Mesurer durée/runners, taille et pagination. Réduire les lectures O(N²) si nécessaires.
8. Segmenter ensuite le registre privé et indexer les empreintes pour ne pas dépendre d'un unique fichier gigantesque. Les contrôles de source de vérité restent privés.

## Interdictions
Aucune fusion, activation de publication, changement d'horaire, modification de JSON public ou déploiement Infomaniak dans cette PR. Les limitations restantes sont documentées et volontairement conservées jusqu'aux tests du moteur transactionnel.
