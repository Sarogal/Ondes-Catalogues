# P'tites Ondes — Pipeline privé Schema.org institutionnel
**20 novembre 2026 — PR préparatoire, sans fusion ni activation.**

## Objectif et justification
Faire passer l'adaptateur JSON-LD générique de la PR #497 d'une simple librairie isolée à une véritable **découverte de pistes privées** avec index officiels et pages filles. Ne pas convertir des métadonnées en preuve de séance visible : ce sont deux circuits séparés.

## Fonctionnement
1. Le registre institutionnel existant (`ptitesondes_institutional_source_policies.json`) fournit le domaine, l'URL exacte de l'index, le préfixe des pages d'événements et l'état des droits. Les sources explicitement restreintes sont exclues de cette collecte.
2. Un petit registre distinct `ptitesondes_schemaorg_source_timezones.json` fixe le fuseau IANA par source, indépendamment des événements. La combinaison est générique : toute nouvelle source institutionnelle déjà examinée peut être inscrite **sans modifier le code du parseur**.
3. `ptitesondes_schemaorg_private_intake.py` lit uniquement l'index HTTP(S) officiel épinglé (sans redirection), sélectionne des liens du même domaine et du préfixe autorisé, puis lit les pages filles via le transport sécurisé existant.
4. Le parseur Schema.org Event n'extrait que des **pistes** : titre, lieu, commune, jour et heure exacte, catégorie indicative ou inconnue. Aucun âge, droit, tarif gratuit ou absence de réservation n'est inféré.
5. Les pistes sont réconciliées par empreinte du lien, titre, lieu, commune, jour et heure. Deux créneaux ne sont pas écrasés l'un par l'autre. Les pistes passées sont archivées du fichier actif. Un échec de site n'efface pas les pistes encore à venir.
6. Stockage atomique uniquement dans `Sarogal/PtitesOndes` branche `automation/ptitesondes-intake`, fichier `automation-intake/ptitesondes/html-schemaorg-hints.json`. Aucun fichier public, patch, publisher ni catalogue n'est touché.

## Activation et sûreté
- Workflow existant `ptitesondes-private-intake-on-public-runners.yml`, sans nouveau cron ni runner privé. Nouvelle étape conditionnée par la **variable distincte** `PTITESONDES_SCHEMAORG_HINTS == enabled`. Elle n'est pas créée par cette PR : la voie reste désactivée par défaut.
- En `preview`, aucune écriture ; en `stage`, écriture sur le checkout Git privé dûment vérifié, puis push privé par le pont déjà protégé. Les rapports publics sont exclusivement des compteurs, jamais les titres, adresses, dates individuelles ou URL des fiches.
- Toute piste porte explicitement `approved=false`, `published=false`, `rights_reviewed=false`, `organizer_verified=false`, `first_party_visible_session_rechecked=false`.
- Les flux existants OpenAgenda, la file des séances HTML déjà attestées, les lieux permanents, les catalogues Grosses Ondes et Infomaniak ne changent pas.

## Limites mesurables
- **Une seule source pilote possède aujourd'hui les deux enregistrements** : Maisons pour Tous Montpellier. Le contrat peut traiter de futures sources variées, mais leur découverte et leur enregistrement indépendants ne sont pas encore automatisés. Il serait erroné d'affirmer une couverture nationale acquise.
- Certains sites n'exposent aucun Schema.org et ne produiront aucune piste. D'autres utilisent des liens d'événements avec paramètres de requête : le système reste strict sur les URL à cette étape et un assouplissement sécurisé doit être étudié séparément.
- Les pistes ne rejoignent pas automatiquement `html-review-candidates.json`. La promotion devra fournir une **preuve exacte visible sur la page**, la confirmation du public familial, de l'organisateur, du lieu/GPS et des droits, puis vérifier les doublons sur le catalogue live.
- Les catégories non musicales non reconnues restent en file de découverte privée ; elles ne sont pas exclues sous prétexte de non correspondance à un libellé connu.

## Validation
Tests hors réseau : lien épinglé/host exact, plusieurs horaires, source inconnue, fichier privé/symlink, idempotence, équité des sources, données ultramarines non expirées prématurément et interdiction de publication. Vérifier CI HTML, lint du pont public et synchroniseur général sur le SHA final.
