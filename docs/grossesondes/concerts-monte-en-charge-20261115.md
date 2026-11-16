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
