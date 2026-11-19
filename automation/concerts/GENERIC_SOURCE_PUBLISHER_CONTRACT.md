# Concerts — Contrat national de publication par salle officielle structurée

## Objectif

Aucune règle ne doit être ajoutée pour un artiste, une date ou un concert
particulier. Un domaine de salle et un préfixe de fiche événement peuvent être
agréés **une fois**, par une PR examinant les preuves officielles, pour permettre
au même vérificateur de traiter ses futurs concerts de manière autonome.

## Deux registres indépendants

- `generic_first_party_venue_specs_v1.json` : sources officielles structurées,
  nom, commune, département, hôte HTTPS exact et préfixe de fiche événement
  `eventPathPrefix` contrôlé (1 à 3 segments). Le manifeste est chargé en
  lecture stricte séparément par le vérificateur et le publisher.
- `reviewed_venue_specs_v1.json` : preuves géographiques indépendantes pour
  **l'ajout de nouvelles salles** au catalogue public. Ne jamais le réutiliser
  comme allowlist de domaines de découverte.

Un nouveau site ne doit jamais être agréé par une simple correspondance entre
un nom de salle et une source de découverte, ni via une mutation du registre
privé. Le rapport `venue-admission-audit.json` sert uniquement au triage.

## Conditions exigées pour chaque fiche publiée

1. Source et fiche HTTPS sur le domaine exact, chemin individuel sous le
   préfixe approuvé, sans redirection, paramètre ni fragment.
2. Salle, commune et département identiques au catalogue public existant.
3. Deux jours distincts d'observation stable avant nouvelle lecture autonome.
4. Un unique événement structuré complet, date, lieu, interprètes nominatifs,
   genre musical explicite associé à **cet événement** et statut confirmé.
5. N'importe quel nombre de nouveaux artistes nommés ; alias et collisions
   protégés. Un invité surprise non identifié n'invente aucun groupe.
6. Heure musicale absente tant que l'ouverture des portes n'est pas prouvée
   être le début du concert.
7. Approbation autonome séparée, puis validation **indépendante** du publisher
   (domaine, chemin, artiste, genre, identité, provenance, doublons et date).
8. Surveillance ultérieure en lecture seule par le même préfixe ; les anomalies
   déclenchent une revue, jamais une annulation automatique.

`official_html_evidence.py` est uniquement une couche d'exploration :
un genre HTML visible ne satisfait pas le contrat de publication structuré.

## Vérifications de déploiement

Le test `tests/test_concerts_generic_publisher_manifest.py` simule une
nouvelle salle, puis deux programmations complètement différentes, dont une
avec plus de vingt artistes, sans correctif par événement. Il contrôle le
publisher réel et la surveillance générique. L'ensemble de la parité Concerts
et des tests du synchroniseur doit réussir sur le commit final.

Aucune nouvelle salle n'est ajoutée au manifeste dans ce chantier. L'activation
d'une nouvelle salle doit faire l'objet d'un audit indépendant réel de son site,
sa géographie, ses fiches et ses genres, puis d'une PR limitée et testée.
