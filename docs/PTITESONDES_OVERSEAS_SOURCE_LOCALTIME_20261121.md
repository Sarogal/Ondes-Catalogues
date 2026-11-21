# P'tites Ondes — contrôle horaire indépendant pour les autres collectivités ultramarines

**21 novembre 2026 — phase de prévalidation, aucune activation ni publication.**

La chaîne de découverte nationale sait chercher les événements de toute la France,
mais son vérificateur OpenAgenda v2 ne reconnaissait initialement que
`Europe/Paris` et les zones de Guadeloupe, Martinique, Guyane, Réunion et Mayotte.

La présente évolution étend la **preuve structurée, strictement non publiable**
à six autres collectivités, sans ajouter de liste de villes ou de lieux connus :

| Collectivité | Code ISO | Fuseaux IANA examinés |
|---|---|---|
| Polynésie française | PF | Pacific/Tahiti, Pacific/Marquesas, Pacific/Gambier |
| Nouvelle-Calédonie | NC | Pacific/Noumea |
| Wallis-et-Futuna | WF | Pacific/Wallis |
| Saint-Pierre-et-Miquelon | PM | America/Miquelon |
| Saint-Barthélemy | BL | America/St_Barthelemy |
| Saint-Martin | MF | America/Marigot |

Références :
- OpenAgenda, structure des lieux : https://developers.openagenda.com/lieux/structure/
- CLDR/Unicode, zones horaires des territoires français :
  https://www.unicode.org/cldr/charts/50/verify/zones/fr.html

## Garanties de sécurité

- **Code ISO du lieu, label territorial et fuseau horaire de l'agenda**
  restent contrôlés ensemble.
- Le décalage de chaque séance doit être celui de la **zone IANA déclarée
  et revue**, y compris les décalages de 30 minutes des Marquises.
- La séance exacte doit être mentionnée dans OpenAgenda ; aucune récurrence,
  date, durée, localisation ou horaire n'est déduit par défaut.
- Les limites de couverture ne constituent pas une liste fermée des lieux.
  Un spectacle sur une place sans numéro ne sera pas exclu pour cette raison.
- Les coordonnées de la fiche OpenAgenda restent **insuffisantes** à elles
  seules : une localisation indépendante comparée à moins de 65 mètres est
  toujours exigée par le même vérificateur. Aucun droit organisateur ou
  droit de réutilisation n'est automatiquement reconnu.
- Les rapports retournent toujours `approval_granted=False`,
  `publisher_connected=False` et `public_writes=0`.

## Limites assumées

Cette étape n'a pas encore branché la recherche nationalisée aux validations
d'accès, à la preuve de l'organisateur, au dédoublonnage final, aux catégories
éditoriales ni à l'écriture du catalogue. Des données administratives
OpenAgenda manquantes ou un fuseau impossible restent en recherche.

La prévalidation ciblée est étendue ; **elle n'atteste pas de la présence
effective d'événements dans chacune des collectivités**, qui doit être mesurée
sur les vrais rapports privés. Les territoires inhabités et TAAF/Clipperton
ne sont pas ajoutés arbitrairement au moteur des sorties enfants.

## Exécution

Tests de non-régression ajoutés dans
`tests/test_ptitesondes_openagenda_v2_direct_evidence.py` :
huit combinaisons code/fuseau (dont trois archipels polynésiens), mauvaises
administrations, mauvais décalages, fausse zone, code de pays étranger.
Ces tests ne consultent aucune API et n'utilisent aucune donnée privée.

**Ne pas fusionner sans autorisation ; aucune modification des cron,
secrets, catalogue public ou branche de production.**
