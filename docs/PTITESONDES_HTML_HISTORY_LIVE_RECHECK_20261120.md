# P'tites Ondes — ancienne date des données ≠ preuve d'un catalogue non consulté

## Anomalie relevée le 20 novembre 2026

La carte contient 549 événements au dernier contrôle, avec des données modifiées le 17/11/2026. Le routeur de prévalidation HTML traitait tout historique dont updated_at avait plus de trois jours comme non vérifié : il confondait **date de modification des données** et **date de consultation de la source**.

Cette règle supprimait les diagnostics utiles des séances familiales alors que l'absence de nouveau contenu est normale. Le catalogue peut rester identique pendant une semaine sans être périmé.

## Correction proposée, sans publication

1. Le routeur de diagnostic HTML distingue désormais la validité d'une date ISO 8601 horodatée, non future, de l'ancienneté du contenu. Une date de modification ancienne n'efface plus un résultat de vérification structurelle de doublons. Les métadonnées absentes, naïves, invalides ou futures demeurent bloquantes.
2. Le véritable point de stockage privé du runner n'autorise aucune nouvelle file à être préparée sans avoir **réellement relu** le catalogue servi depuis l'URL HTTPS GitHub Pages figée et sans avoir comparé l'empreinte canonique à celle du dépôt. Il réutilise le module existant de contrôle live, à transport HTTPS strict et sans redirection.
3. Une concordance est admise même si la dernière modification du JSON a plus de 24 heures, car la relecture est récente. Un écart de données, une réponse inaccessible ou un rapport falsifié bloque la préparation du lot.
4. Si ce blocage se produit, le backlog privé existant n'est pas supprimé, aucun patch n'est produit et aucun événement n'est publié.

## Garantie d'indépendance

Le contrôle live est appelé depuis le runner de confiance, et non à partir d'une URL ou d'un drapeau fourni par le collecteur. Cette vérification sert à sécuriser le **stockage de candidats pour revue**, pas à attester des droits, de la provenance, de la géolocalisation ou de l'organisateur.

La vérification du catalogue et de ses doublons devra être répétée à l'instant de l'admission finale par le futur publisher non musical. Le moteur musical et les événements existants restent inchangés.

## Tests

- Date de changement ancienne mais horodatée : revue privée possible, sans publication.
- Date future, date non horodatée, valeur absente : refus de la prévalidation.
- Snapshot public relu, égal au dépôt : transfert privé de diagnostic seulement.
- Snapshot divergent, contrôle non fiable ou date incohérente : arrêt avant tout traitement.
- Tous les contrôles de CI restent obligatoires ; aucune fusion sans accord explicite.
