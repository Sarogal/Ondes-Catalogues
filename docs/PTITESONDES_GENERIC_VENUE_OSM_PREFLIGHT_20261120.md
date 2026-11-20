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

## Extension : corroboration IGN/BAN sans liste de villes

`scripts/ptitesondes_generic_venue_ign_corroboration.py` reprend le niveau
de rigueur du contrôleur IGN/BAN déjà présent pour quatre bâtiments homologués
(`ptitesondes_independent_ign_venue_recheck.py`), mais le **généralise**
aux lieux nouvellement découverts : pas de noms, communes ou adresses épinglés.

Après un résultat OSM au nom exact et sans ambiguïté, une requête IGN/BAN
unique est possible **seulement si le POI fournit explicitement numéro,
rue et code postal**. La réponse doit être un numéro de rue exact,
dans la même ville avec le même code postal, score ≥ 0,95 et coordonnées
à 65 mètres maximum du point nommé OSM **et** du centre source. Une rue
sans numéro, un centroïde de commune, une adresse ambigüe, une divergence
de points ou une erreur réseau ne déclenchent aucune admission.

Le rapport privé distingue :
- `independent_address_matches` : **nombre de lieux avec une adresse
  corroborée**, sans homologation officielle ;
- `leads_with_independent_address_hint` : nombre de pistes
  potentiellement concernées (ce ne sont **pas** des événements débloqués) ;
- `verified_venue_leads` : **toujours zéro** tant que le mécanisme
  d'attestation officielle du lieu n'est pas construit ;
- `publication_ready=false`, `public_writes=0` sans exception.

Le mode par défaut ne fait **aucun accès réseau**. Le flag explicite
`--live-probe` lance ODS, Overpass puis IGN/BAN, sans aucune écriture
publique. Le chemin du backlog **et** du rapport doivent se trouver hors
du checkout public. Aucun workflow de production n'invoque ce flag.

## Limites opérationnelles restantes

- La proximité du point OSM avec le centre OpenAgenda/ODS ne prouve pas
  l'identité ou la disponibilité du lieu, seulement une cohérence
  géographique partielle.
- Un lieu sans adresse postale (parc, place, espace temporaire) exige
  une voie distincte de preuve de l'emprise publique et du nom, jamais
  l'invention d'une adresse numérotée.
- Une donnée OSM/BAN ne peut pas remplacer la preuve de l'établissement
  par son site officiel, ni la confirmation de chaque séance et de son public.
- Les UID absents du miroir ODS restent à traiter par la PR #503 et un
  pont de lecture OpenAgenda v2, **sans** assimiler une preuve directe
  de l'organisateur à une source indépendante.
- Le publisher reste volontairement déconnecté de cette PR.

## Extension : preuve générique de l'identité officielle de l'établissement

`ptitesondes_generic_venue_official_proof.py` ajoute une vérification
**purement hors réseau** des données structurées `schema.org/Place`
(et sous-types explicitement documentés) sur la page officielle d'un lieu.

Conditions cumulatives :
1. La preuve OSM + adresse IGN/BAN a réussi.
2. L'URL de la page officielle est fournie **indépendamment du collecteur
   et des attributs OSM** et appartient à un hôte approuvé par un registre
   distinct. L'outil refuse les domaines OpenAgenda/ODS/OSM/IGN comme preuve
   d'identité institutionnelle.
3. Une seule entité `Place` porte le nom exact, la commune, la rue,
   le numéro et le code postal corroborés ; toute contradiction des coordonnées
   éventuelles bloque la qualification géographique.
4. Si l'URL officielle n'existe pas, si le domaine n'a pas été approuvé
   indépendamment, ou si la page ne contient pas de `Place` exploitable,
   le dossier reste en attente, sans inventer l'identité.

Cette couche est intégrée au moteur en **injection de preuves uniquement** :
`official_page_get` et `approved_official_hosts` doivent être fournis par
un futur connecteur institutionnel authentifié ; ils ne sont **pas**
alimentés par le backlog privé ou par un champ `website` de la carte OSM.
Ainsi **aucun site externe arbitraire n'est automatiquement homologué**.

Même dans le cas positif, le rapport `location_evidence_complete_for_private_review`
n'est **pas** une permission de publier : `verified_venue_leads=0`,
`publication_ready=false`, `public_writes=0`. Il manque encore le
raccordement authentifié des sources officielles, l'admission de chaque séance
et le publisher, explicitement hors périmètre de cette PR. Le test d'intégration
couvre l'ensemble ODS → OSM → IGN/BAN → HTML officiel, sans connexion réseau.

## 20 novembre — provenance municipale automatisable via DILA

**Mesure actualisée du backlog privé** : **449 dossiers**, dont **149 classés
`venue_gps_unverified`**, toujours **79 couples ville+lieu distincts**
(52 communes lors de la mesure initiale). Les 209 admissibles au premier
filtre ne sont pas prêts à publier.

La Direction de l'information légale et administrative (DILA) publie
l'annuaire officiel de l'administration et des services publics, source :
- https://www.data.gouv.fr/dataservices/api-annuaire-de-ladministration-et-des-services-publics
- API `https://api-lannuaire.service-public.gouv.fr/api/explore/v2.1`
- Données `api-lannuaire-administration`, champs `nom`, `pivot`,
  `code_insee_commune`, `adresse`, `site_internet`, `categorie`,
  `statut_de_diffusion` et `url_service_public`.

Le module **`scripts/ptitesondes_dila_municipal_domains.py`** fournit
la vérification générique d'un **domaine municipal indépendant** :
- recherche bornée par nom de commune et `mairie`, sans liste de villes ;
- revue exacte du nom de mairie, du code INSEE, de l'adresse en France,
  du caractère public de la fiche et de l'éditeur DILA ;
- vérification de la présence d'un unique résultat municipal non ambigu ;
- hôtes HTTPS des sites répertoriés par DILA (jamais une URL inventée
  ou déclarée `official=1` par OpenAgenda) ;
- refus des réseaux sociaux, hébergeurs mutualisés et domaines trompeurs ;
- restriction aux sites de la commune identifiée, sans accorder confiance
  à l'ensemble des sites en `.fr` ou `.gouv.fr`.

La preuve DILA est raccordée **par injection d'une lecture du répertoire**
dans `inspect_group()`/`audit()`. Lorsqu'un lecteur DILA est fourni,
il **remplace** la liste d'hôtes déclarée par l'appelant : une erreur de
l'annuaire, une mairie ambiguë ou un hôte différent bloque la preuve du lieu.
Le contrôle d'identité sur une page officielle reste strict et séparé du
contrôle du site municipal. Un domaine municipal **ne suffit pas** à prouver
qu'un événement se tient dans le lieu mentionné.

**Aucune activation en production :** le CLI de préflight n'a pas encore
de découverte fiable du détail officiel du lieu à ouvrir ; les tests
simulent des cas positifs/négatifs hors réseau. Pour achever l'autonomie,
il faut obtenir la page d'établissement au sein du domaine DILA confirmé,
vérifier l'identité/coordonnées puis transmettre un résultat réutilisable
au publisher après toutes les autres vérifications de la séance.

**Attribution future en cas de réutilisation des données DILA** :
mentionner « Service-Public.gouv.fr / DILA », la source et la date,
selon la notice officielle (aucun nouveau jeu de données n'est publié ici).

Les parcs et lieux éphémères sans adresse numérotée nécessitent une branche
géographique distincte ; la voie IGN/BAN numéro de rue ne doit pas les
bloquer définitivement. `verified_venue_leads=0`, aucun raccordement
publisher, aucun déploiement GitHub Pages/Infomaniak.
