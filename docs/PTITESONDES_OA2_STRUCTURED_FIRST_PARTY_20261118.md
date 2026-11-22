# P'tites Ondes — preuves horaires génériques sur pages institutionnelles structurées

18 novembre 2026. **PR préparatoire / lecture seule / sans publication, sans droits d'écriture.**

## Problème traité

Le moteur OpenAgenda v2 #371 dispose de la preuve directe de séance, mais l'adaptateur organisateur existant `ptitesondes_openagenda_v2_organizer_bridge.py` exige de lire la date et l'horaire dans le même bloc de texte HTML visible. Certaines pages institutionnelles fournissent un objet `Event` schema.org avec un `startDate` précis dans leur JSON-LD, alors que le texte visible indique la date et l'heure autrement, voire les affiche via JavaScript. Elles sont aujourd'hui refusées à l'étape de corroboration structurée.

Cette PR propose un **second chemin de diagnostic**, non une substitution automatique ni un assouplissement de la publication.

## Vérifications réelles, indépendantes, réutilisables

- Contrôler la preuve OpenAgenda API v2 déjà calculée, sur un seul UID et une seule date explicite. Refuser les UID couvrant plusieurs dates tant que le regroupement n'est pas résolu.
- Recevoir l'hôte et l'URL institutionnels exacts d'un **registre revu séparément** du backlog ; la page HTTPS doit avoir été récupérée sans redirection. Interdiction d'utiliser une URL prétendument officielle provenant de la piste OpenAgenda.
- Exiger dans le texte visible de la page institutionnelle le titre, le lieu, la commune **et un signal familial/enfants**. Refuser explicitement les séances adultes, annulées, complètes ou reportées.
- Vérifier séparément dans le JSON-LD institutionnel un objet `Event` ou sous-type, même titre exact, lieu et commune cohérents, statut `EventScheduled` si déclaré, et **chaque horaire exact du jour** en tenant compte du fuseau OpenAgenda. Aucun horaire inventé.
- Exiger tous les horaires de la preuve OpenAgenda. Une seule concordance ne suffit pas à valider un programme comportant deux séances le même jour.
- Produire exclusivement un rapport anonymisé de conformité structurelle : zéro fiche, zéro patch, zéro nouveau droit et aucune donnée privée renvoyée.

## Limites non négociables

Ce chemin n'atteste pas la propriété effective du domaine institutionnel, la licence et les droits, l'âge exact, l'accès familial, la réservation, les doublons historiques, les dates multiples, la catégorie éditoriale ni la publication. Même si la page et le JSON-LD concordent, l'approbation et le publisher restent à **false**.

Les données JSON-LD peuvent être obsolètes. Un conflit avec la page visible ou les horaires OpenAgenda bloque le résultat ; une page officielle seulement soupçonnée ou auto-déclarée n'est pas une preuve indépendante. Ce module n'interroge aucun site, ne lit aucune clé et ne modifie aucune sortie.

## État

Les tests CI de la PR utilisent uniquement des événements synthétiques et des pages HTML artificielles. Ils ciblent les fausses URL institutionnelles, les contradictions de lieu/date, le fuseau, le statut et l'accès adult-only, les multi-séances et le masquage des identifiants. Aucun run authentifié sur le backlog privé ni aucune nouvelle publication ne doivent être revendiqués par ces tests.

**Ne pas fusionner avant autorisation explicite**. Pour préparer l'industrialisation, comparer en lecture seule ce chemin au validateur HTML visible existant sur des pages institutionnelles réellement homologuées ; conserver une preuve de provenance et des compteurs anonymes.
