# P'tites Ondes — adaptateur national générique RSS / Atom de première partie
**18 novembre 2026 — PR empilée de diagnostic uniquement, non activée.**

## Contexte réel
La branche de diagnostic #388 propose un chemin première-partie depuis un index
HTML vérifié indépendamment. En complément, de nombreux sites institutionnels
utilisent RSS 2.0 ou Atom pour lister des pages d'événements. Ces formats ne
doivent **jamais** constituer à eux seuls une preuve de séance, d'âge, d'adresse,
de droit de réutilisation ni d'autorisation de publication.

À titre d'exemple, l'URL officielle
`https://mediatheques.villeurbanne.fr/agenda/rss-2/` existe et expose
des événements de médiathèques, mais lors du contrôle du 18/11 son MIME
est `text/html`. **Ce n'est pas un flux RSS XML reconnu par ce module.**
Cette page relève de l'adaptateur d'index HTML ou d'un autre adaptateur
institutionnel ; on ne doit pas lui attribuer un support RSS sans preuve.

## Fonctionnalités apportées
- `ptitesondes_openagenda_v2_official_feeds.py` ne réalise aucun accès réseau.
- Entrée : `lead` non fiable, `reviewed_feed` issu d'un registre distinct
  (`approved_host`, `exact_feed_url`, `feed_format`), et `fetched_feed`
  téléchargé par un lecteur borné, sans redirection, depuis l'URL exacte.
- XML RSS 2.0 et Atom namespace 2005 uniquement ; MIME XML contrôlé,
  charge utile bornée (450 000 caractères), maximum 600 items, DTD/ENTITY
  refusés pour prévenir injection et expansion.
- L'intitulé d'un item est confronté au titre exact normalisé de la piste ;
  uniquement un lien de page événement HTTPS sur le **même hôte épinglé**
  peut être proposé.
- Plusieurs liens distincts pour le même titre : attente, jamais sélection
  d'une fiche arbitraire.
- `pubDate` dans RSS est la **date de publication de l'article**, pas une
  preuve du créneau de l'événement : elle n'est jamais utilisée pour dater.
- URL/identifiant de candidat ne figurent pas dans les résumés publics.

## Chaîne de confiance
`diagnose_feed_candidate(case, reviewed_feed, fetched_feed, today)`
n'accepte jamais de lien d'organisateur fourni par le lead. Il construit
l'épingle depuis le flux institutionnel, exige un nouveau fetch de la page
événement avec URL finale exacte et passe les données à
`diagnose_candidate` pour les contrôles de source OpenAgenda, IGN/BAN,
date, horaires et public familial.

Le résultat est un **diagnostic de structure et seulement de structure**.
`approval_granted=False`, `publisher_connected=False`, `public_writes=0`
même en cas d'exactitude complète ; les autres portes restent :
propriété institutionnelle, licence/droits, âge et accès exacts, historique,
regroupement multi-jours, classification éditoriale et autorisation de
publication.

## Limites
- Pas de détection automatique de liens de feed (la preuve de confiance
  exige un registre indépendant) ;
- pas de flux JSON propriétaire, ICS/iCal, JavaScript-only, pagination,
  XML aux formats non RSS/Atom ;
- titres abrégés, intitulés similaires ou multiples toujours retenus à
  l'examen, pas automatiquement rapprochés ;
- un même UID sur plusieurs dates nécessite toujours le regroupement ;
- un flux RSS peut être un miroir de la source et ne fait pas automatiquement
  foi des droits ou de la propriété institutionnelle.

## Suivi
Exécuter d'abord un essai en lecture seule dans la **branche privée** sur
des index/flux d'organisateurs officiellement attestés. Ne jamais transmettre
le backlog ou les liens candidats aux workflows et rapports publics.

**Aucun moteur de publication, GitHub Pages, Infomaniak, secret ou cron
n'est modifié par cette PR ; aucun déploiement ni fusion autorisé.**
