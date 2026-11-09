# P'tites Ondes — recontrôle privé des séances de lieux

Le rapport `lieux-agenda-candidates.json` est constitué de pistes découvertes
sur les programmes des établissements. Il **n'autorise aucune publication**.

Le module `scripts/ptitesondes_place_agenda_preflight.py`, appelé par le cycle
**Lieux** déjà programmé sur les runners publics, reprend les pistes datées et :

- vérifie l'identité du lieu dans le catalogue public permanent et la route de
  collecte préapprouvée (programme institutionnel mille formes ou Toulouse,
  fiche événement municipale Totems) ;
- refuse horaires, fuseaux, plages et dates incohérents, candidats non
  homogènes, sources non inscrites ou extracteurs inconnus ;
- recherche une fiche déjà publiée ayant le même titre, la même date et un
  lieu cohérent (nom exact ou coordonnées officielles à 65 mètres) ;
- relit à nouveau la page officielle **exacte** et réexécute le parseur
  spécifique ; une date ou une heure modifiée n'est plus confirmée ;
- refuse les erreurs réseau, les pages absentes ou excessives et borne le
  nombre de nouvelles pages demandées.

La sortie `automation-intake/ptitesondes/lieux-agenda-preflight.json` est
enregistrée **uniquement** dans la branche privée
`Sarogal/PtitesOndes:automation/ptitesondes-intake` lorsque le collecteur
fonctionne en mode `write`. Aucun nouveau cron, runner privé ni droit
d'écriture public n'est ajouté.

Le meilleur état possible à ce niveau est
`source_reconfirmed_private_only`. Les attributs
`safe_to_publish` et `publish_authorized` restent **false**, même quand
la fiche officielle n'a pas changé. Une source municipale revérifiée n'est pas
à elle seule une seconde preuve indépendante. L'extension des catégories
non musicales, les preuves géographiques complémentaires et la procédure de
publication restent strictement séparées.

Les sorties existantes et les six lieux permanents publiés ne sont jamais
modifiés par ce recontrôle.
