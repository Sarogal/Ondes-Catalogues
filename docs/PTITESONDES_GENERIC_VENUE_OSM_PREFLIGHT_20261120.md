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

## Contrôle des URL de lieux OpenAgenda contre les sites municipaux DILA

Les fiches de lieu OpenAgenda v2 contiennent un champ facultatif
`location.website`, indiqué dans la documentation OpenAgenda :
https://developers.openagenda.com/en/lieux/structure/.

`verified_oa_location_website()` permet de retenir ce lien en
**candidat de lecture**, mais uniquement en présence cumulée :
- d'un événement OA v2 public et présentiel, d'un UID attendu, d'un
  lieu et d'une commune cohérents ;
- d'un site HTTPS dont le domaine appartient au site municipal déclaré
  pour **la même commune** dans l'annuaire DILA authentifié ;
- d'aucune erreur, ambiguïté ni contradiction de domaine.

La propriété `location.website` d'OpenAgenda n'est **pas** une preuve
d'institution : elle sert seulement à trouver la page à lire. L'adresse
municipale du domaine provient d'un registre administratif distinct.

À ce stade, **aucune exécution réseau réelle de ce pont n'est activée** :
son API est testée hors réseau et prête à être utilisée par un adaptateur
de récupération OA v2 + DILA dans l'espace privé. Le programme CLI
actuel continue de ne publier ni ne valider de sortie. La page exacte
doit ensuite passer `official_venue_page_proof` sur les attributs
Schema.org du lieu, puis les vérifications complètes de la séance.

## Lecteur municipal utilisable en prévisualisation privée explicite

Le nouveau `scripts/ptitesondes_municipal_official_page_reader.py` clôt
l'écart entre des adaptateurs isolés et un **lecteur de pages réellement
appelable** : à partir d'un backlog privé et de la liste privée des UID des
agendas retenus, il recoupe le slug OA, l'UID événement, le nom exact du lieu,
la commune et `location.website`, obtient la fiche municipale DILA,
puis charge uniquement une page HTTPS relevant du domaine municipal approuvé.

Le CLI `ptitesondes_generic_venue_osm_preflight.py` propose désormais
une option **désactivée par défaut** `--official-municipal-pages` :
```bash
# À exécuter uniquement dans un runner isolé, sans publication ni artifact public.
# La clé de lecture OPENAGENDA_READ_KEY est fournie en secret d'environnement.
python scripts/ptitesondes_generic_venue_osm_preflight.py \
  --backlog /espace-prive/automation-intake/ptitesondes/backlog.json \
  --private-source-config /espace-prive/automation/sources.json \
  --output-private-report /espace-prive/venue-proof-preview.json \
  --day 2026-11-20 --live-probe --official-municipal-pages
```

La commande exige explicitement `--live-probe`, un `sources.json`
privé hors checkout public, et `OPENAGENDA_READ_KEY`. Le mode par défaut
n'effectue **aucun** appel réseau. Aucune action programmée n'a été ajoutée,
aucun secret n'est affiché ni ajouté au dépôt.

Le lecteur refuse tout agenda non enregistré dans la configuration privée,
UID OA divergent, site Internet absent, source DILA ambiguë, URL externe
hors domaine municipal, redirection, mauvais type MIME ou page trop volumineuse.
Une seule commune est interrogée une fois par cycle grâce au cache privé ;
au plus trois UID sont comparés pour un même lieu très représenté.
Ces trois UID **ne valident pas les autres séances** : toutes les vérifications
d'événements restent individuelles.

Les rapports contenant des noms de lieux, URL ou coordonnées doivent demeurer
**strictement privés**. Le fichier source `docs/ptitesondes/sorties.json`
et le publisher ne sont pas utilisés par cette branche.

**Limites connues** :
- Les pages de lieux sans `schema.org/Place` explicite restent bloquées,
  même si l'établissement est réel ; enrichir l'extraction officielle
  sans inventer de preuves.
- Les sites privés de lieux (hors domaine municipal DILA) et les espaces
  publics sans numéro exigent d'autres registres institutionnels.
- Les dossiers avec UID absent du miroir ODS sont encore dépendants du
  correctif #503 et de la preuve OA directe.
- Aucun lancement réel de cette commande contre le backlog privé n'est
  revendiqué dans ce chantier : son comportement positif est couvert
  par des tests hors réseau. **Zéro nouvelle sortie effectivement admise**.
