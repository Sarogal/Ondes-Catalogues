# Concerts — emplacements événementiels sans salle permanente

## Périmètre
Ce contrat est destiné aux concerts officiellement confirmés dans une place,
une rue, un parc, une scène provisoire ou un autre site sans salle historique.

Il **ne crée aucune confiance automatiquement** depuis une source de découverte,
un ICS, un billet, un géocodeur ou une position OpenStreetMap. Une localisation
n'est pas une preuve d'existence du concert. Aucun artiste ni événement réel
n'est signé ou ajouté par cette PR.

## État des composants
- Le collecteur de tournées reconnaît déjà `newVenueToReview=true`.
- Le publisher possède une branche alternative
  `independent-event-site-v1` dans `scripts/concert_event_site_contract.py`.
- Le **producteur automatique de ces attestations** dans
  `official_recheck` n'existe pas encore. C'est le prochain composant
  indispensable avant de déclarer ce chemin autonome.

## Préconditions pour l'approbation privée
1. Une fiche d'événement spécifique, avec ID, date complète, URL officielle,
   artiste, programmation, genre et lieu, a été **indépendamment revérifiée**.
2. L'URL exacte relève d'un artiste ou promoteur dont la source est déjà
   revue dans `artist-tour-sources.json` ; le domaine du détail correspond.
   Un nouveau site officiel est revu en tant que source **une fois**, et non
   comme autorisation automatique de ses futures annonces.
3. L'approbation du site (`venueApprovals[]`) est distincte de l'approbation
   du concert (`approvals[]`), mais les deux ont le même `eventId`,
   `eventDate`, `eventOfficialUrl`, `venueId` et date de revue.
4. Deux preuves signées sont présentes : l'annonce de l'événement donnant
   identité, date et localisation ; un objet OSM nominatif, dont les coordonnées
   correspondent exactement à la localisation approuvée. Ce second objet est
   **géographique seulement** et ne confirme ni affiche, ni date, ni genre.
5. La commune, le département, le code postal, le nom du site et la précision
   géographique sont connus. Aucun centre de ville n'est substitué aux
   coordonnées absentes. Aucune preuve n'est inférée d'un nom d'artiste.
6. Le lieu public reçoit un ID stable dérivé de son nom, sa commune et son
   objet géographique OSM ; plusieurs concerts peuvent partager ce repère,
   mais aucun n'hérite automatiquement de la preuve événementielle du premier.
7. Le publisher vérifie l'événement complet, puis ajoute le site et le concert
   au **même lot**. Si le concert n'est finalement pas publié, le site provisoire
   disparaît de la sortie du lot. Les dossiers d'approbation privés restent
   disponibles pour revue.

## Champs privés
`venueKind = independent-event-site-v1`, `locationKind` parmi
`public-square`, `street`, `park`, `temporary-stage`, `outdoor-site`.

`eventBinding` contient l'ID, la date, l'URL officielle du concert,
`authoritySourceUrl` (source revue) et `authorityArtistId`.

`officialEvidence` comprend `official-event-location` et
`independent-osm-site`, chacune avec les champs effectivement vérifiés et
leur date de contrôle. Les identifiants de la salle publique conservent les
champs géographiques du catalogue : nom, adresse, code postal, ville,
département, région, latitude, longitude, `geoPrecision`, `geoSource`.

## Étape suivante vers une autonomie réelle
Développer un vérificateur indépendant de **concerts de tournées** qui
récupère les preuves officielles, recoupe la localisation sur une source
géographique externe et émet les deux approbations privées **uniquement**
lorsque chaque contrôle est réel et documenté. Étendre ensuite les sources
officielles aux organisateurs et collectivités non associés à un artiste
catalogué, sans créer une autorisation par concert.

Mesurer sur le terrain le nombre de concerts ajoutés via ce chemin ; les
42 candidats de lieux inconnus au 19/11 ne sont **pas** 42 publications prêtes.
