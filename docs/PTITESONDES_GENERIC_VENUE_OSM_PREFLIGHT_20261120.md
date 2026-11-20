# P'tites Ondes — découverte générique des lieux encore inconnus (20/11/2026)

## Périmètre, mesure réelle
Relecture du backlog privé `automation/ptitesondes-intake` et des registres publics
au 20 novembre 2026 : **441 pistes**, **141 bloquées au premier filtre
pour lieu/GPS**, représentant **79 couples exacts (commune, lieu) dans
52 communes**. **36 lieux sont récurrents** ; les 10 plus fréquents
concentrent **43 pistes**. Le rapport privé de qualification du 20/11
confirme 141 dossiers et 209 admissibles au premier filtre.

Ces métriques concernent des pistes en attente et non des séances publiables.
Le total de **dossiers réellement débloqués par cette PR est zéro**.

## Nouveau code
`scripts/ptitesondes_generic_venue_osm_preflight.py` :
- reprend la classification `admission_failure_group()` effective ;
- regroupe une seule fois les entrées par commune + lieu, pas par séance ;
- traite au plus **12 lieux par exécution**, avec rotation déterministe ;
- exige un UID source exact et compare identité du lieu et coordonnées issues
  des fiches ODS, **uniquement comme centre de recherche non fiable** ;
- interroge exclusivement deux endpoints Overpass configurés en dur, sans
  redirection, avec un budget strict sur les réponses ;
- retient uniquement un objet OSM indépendant au **nom exact**, situé
  à moins de **65 m**, sans contradiction explicite de commune ;
- distingue **aucun**, **un** ou **plusieurs** objets candidats et les erreurs ;
- produit des résultats de revue **privés**, sans exporter de coordonnées
  ou de noms de lieux dans les résumés publics ;
- ne modifie **ni** le registre `VENUES`, ni les fichiers publics, ni le
  moteur de promotion, ni les workflows GitHub Actions.

Le simple point OSM ne prouve pas l'adresse officielle, l'organisateur,
l'identité de l'établissement, la date, l'horaire ni le public familial.
**Tout résultat reste non attesté et aucune publication n'est possible.**

## Exécution (réservée au contexte privé)
Le script consomme le **backlog privé déjà téléchargé dans un runner
authentifié**. Par défaut la commande ne contacte aucun site externe :

```bash
python scripts/ptitesondes_generic_venue_osm_preflight.py \
  --backlog /chemin/prive/backlog.json \
  --output-private-report /chemin/prive/venue-osm-report.json \
  --day 2026-11-20
```

`--live-probe` autorise explicitement la lecture bornée ODS + OSM.
Ce flag ne doit pas être ajouté à un workflow de production sans
une nouvelle validation, ni sans chemin sûr de stockage dans la branche
privée. Les deux autres sources d'échec (UID absent du miroir,
preuve officielle de lieu indisponible) demeurent des blocages.

## Pour passer ensuite de découverte à admission
1. Vérifier la fiche officielle du lieu : nom, commune, adresse physique
   ou emplacement extérieur, et provenance institutionnelle réelle.
2. Corroborer l'adresse, le bâtiment ou la place par un **fournisseur
   géographique indépendant** ; interdire les correspondances approximatives
   ou ambiguës, sans imposer une salle de spectacle préenregistrée.
3. Introduire une attestation de lieu réutilisable dans la vérification
   `registry_location()`, avec contrôle d'identité, expiration et relecture
   des preuves. Aucune donnée du collecteur n'est une preuve indépendante.
4. Vérifier **chaque séance** (date/heure/public/organisateur), doublons,
   droits de réutilisation, statut et publication append-only.
5. Tester le chemin publisher -> GitHub Pages -> carte avant activation
   ou déploiement, avec autorisation explicite.

Cette PR prépare une recherche générique mais ne prétend pas atteindre
l'autonomie totale. Pas de fusion, de nouveau workflow activé ou de
modification de la production.
