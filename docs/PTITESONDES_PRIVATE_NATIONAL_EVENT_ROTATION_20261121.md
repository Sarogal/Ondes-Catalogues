# P'tites Ondes — orchestration privée des nouveaux agendas OpenAgenda

**21 novembre 2026 — développement en prévisualisation, pas de planification activée**

## But

Le scanner national de #547 produit une liste de 0 à 160 nouveaux agendas publics à explorer par lot. Le lecteur d'événements de #553 sait parcourir les événements d'**un** agenda, mais demander manuellement chaque index n'est pas suffisamment autonome.

Le nouveau `scripts/ptitesondes_private_national_event_campaign.py` orchestre plusieurs lectures à la suite, **dans un espace privé uniquement**, avec un état conservant la progression. Il n'utilise pas de liste de lieux autorisés et n'exige pas de numéro de rue pendant la découverte.

## Mécanisme

- Un rapport d'index privé #547 est l'entrée obligatoire ; aucune donnée privée ne doit être committée dans Ondes-Catalogues.
- Jusqu'à **8 segments par lancement**, chaque segment consulté par le lecteur #553 étant plafonné à trois pages de 20 événements. Le plafond protège les appels API, pas le nombre de séances d'une représentation.
- Un **curseur de suivi** lie l'empreinte SHA-256 de l'index, la date de campagne, l'agenda sélectionné et son curseur de pagination des événements. Après un agenda terminé, le moteur passe automatiquement au suivant.
- Chaque segment fait l'objet d'un **fichier distinct 0600** contenant seulement des **pistes de recherche**. L'état est écrit atomiquement après le rapport. Un deuxième passage reprend là où le premier s'est arrêté. Si le processus s'interrompt entre l'écriture du rapport et celle du checkpoint, le rapport est récupérable sans relire le réseau seulement si son agenda, son segment, son curseur initial, la date et l'empreinte du fichier d'index sont parfaitement identiques.
- Un verrou privé exclusif empêche deux exécutions simultanées ; un rapport existant sans checkpoint correspondant n'est récupéré automatiquement que si sa provenance et son curseur sont exactement validés. Toute incohérence exige une intervention privée contrôlée.
- L'option `--execute-live` est obligatoire pour le réseau. Par défaut le script contrôle les fichiers et annonce la progression, sans réseau ni mutation d'état.
- En sortie standard, **uniquement des compteurs**, sans titre, lieu, URL, agenda UID, ni données privées.

## Renforcements de reprise et de sélection

- Même si plusieurs appels préparent un plan avant l'acquisition du verrou, **le checkpoint est relu sous verrou** avant toute consultation ou récupération de rapport. Le second appel ne peut plus faire reculer l'index avec son plan périmé.
- Les informations éditoriales sont recherchées dans le titre, la description courte **et la description longue** fournie par l'API. Un titre d'œuvre opaque ne devient pas un motif de rejet lorsque la nature du spectacle apparaît dans le texte.
- Un événement OpenAgenda de statut **2 (reprogrammé)** reste une piste de recherche. Il porte le drapeau `requires_reprogramming_verification` : ses nouveaux horaires doivent toujours être vérifiés indépendamment. Les statuts déplacé en ligne, reporté sans nouvelle date, complet et annulé ne sont pas admis par cette exploration.
- Un lieu annoncé sans commune, ou une commune sans nom de salle, déclenche encore une recherche géographique en aval ; aucune coordonnée n'est inventée.
- Ces règles créent seulement des **pistes privées non publiables**, jamais des ajouts automatiques au catalogue.

## Commande illustrative (espace privé)

Les chemins ci-dessous sont indicatifs : ils ne doivent **pas** pointer dans le dépôt GitHub public. L'environnement doit fournir une clé OpenAgenda **publique de lecture** dans `OPENAGENDA_READ_KEY`.

```bash
python scripts/ptitesondes_private_national_event_campaign.py \
  --private-agenda-index-report /espace-prive/rapports/index-001.json \
  --private-output-dir /espace-prive/recherche-evenements/index-001 \
  --day 2026-11-21 \
  --max-steps 8
```

Ajouter `--execute-live` pour exécuter les consultations réelles.

La campagne avance au plus sur 8 segments dans une invocation : elle doit être relancée depuis le même dossier privé pour poursuivre. Les échecs ne confèrent aucune admission. La récupération d'un segment déjà écrit est couverte par les tests ; un verrou restant après un arrêt brutal impose toujours une vérification et une remise en état contrôlées.

## Ce qui reste à faire pour la production

1. Brancher un orchestrateur **privé planifié** et un watchdog aux runners publics sans jamais exposer les rapports ou les clés. Aucun nouveau cron dans cette PR.
2. Prévoir un watchdog pour les verrous orphelins et les interruptions persistantes ; la récupération contrôlée d'un rapport déjà écrit est désormais implémentée et testée hors réseau.
3. Sélectionner les agendas signalant des événements utiles et remonter uniquement les fiches de musique, conte ou spectacle jeunesse avec suffisamment d'indices, sans perdre les titres d'œuvres trop génériques.
4. Vérifier les preuves officielles de date, salle ou lieu public, accès enfant, organisation, droits de réutilisation, géolocalisation et doublons. **Une fiche de recherche n'est pas une publication**.
5. Vérifier la couverture France métropolitaine, Corse et outre-mer à partir de rapports privés réels, y compris les lieux sans numérotation.

## État

**Aucune exécution live de campagne, aucune découverte confirmée par ce module, aucune fusion, aucune publication et aucune modification des workflows planifiés.**

Documentation API : https://developers.openagenda.com/10-lecture/
