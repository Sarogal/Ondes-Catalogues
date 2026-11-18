# P'tites Ondes — Routeur générique de calendriers WordPress EventON
**18 novembre 2026 — développement isolé, hors production.**

## Source d'observation

Inspection en lecture seule de l'agenda public des médiathèques de Villeurbanne
`https://mediatheques.villeurbanne.fr/agenda/rss-2/` :

- La page est de type HTML et utilise des ancres d'événements du calendrier
  WordPress EventON/evcal, avec les classes `desc_trig evcal_list_a`.
- La chaîne `evc_<timestamp><identifiant>` se trouve dans l'`id` de l'ancre.
  Exemple observé : `evc_179559900022790` pour « Bouquins câlins »
  (25/11/2026). L'URL événement indiquée est sur le même domaine.
- La date et l'horaire sont présentés dans des éléments séparés, souvent
  des `<em>`, non dans le texte de l'ancre. Les séances de même titre peuvent
  avoir des URL distinctes.
- Ces métadonnées doivent uniquement servir à trouver une page à vérifier,
  jamais à certifier une séance.

Ce mécanisme est celui d'une famille de calendriers, pas une exception
à « Bouquins câlins » ou à Villeurbanne.

## Algorithme isolé
`ptitesondes_openagenda_v2_eventon_index.py` :

1. L'opérateur fournit un domaine institutionnel **revu séparément** et
   l'URL HTTPS exacte d'un index public. Le candidat OpenAgenda ne choisit
   jamais ces informations.
2. Un lecteur de confiance télécharge cette page sans redirection, en
   respectant des bornes. Le parseur pur de la PR analyse jusqu'à
   2 Mo de HTML et 2400 liens maximum.
3. Il considère seulement les liens HTML visibles ayant les classes
   EventON attendues, un ID `evc_<10 chiffres de timestamp><id>`, un
   intitulé strictement identique au titre normalisé de la piste et une
   URL événement HTTPS du même hôte.
4. Le timestamp de l'ID est interprété comme **indice de jour uniquement**.
   Une tolérance maximale d'un jour prend en compte des calendriers stockant
   la date locale dans un timestamp UTC ; ce choix n'autorise aucune
   date ou heure. Les autres preuves indépendantes sont indispensables.
5. Si plusieurs liens plausibles différents restent après filtrage,
   le routeur refuse de choisir.
6. La page trouvée doit être récupérée à son URL exacte puis soumise
   à `diagnose_eventon_candidate`, qui applique les contrôles existants
   GPS/IGN/BAN, UID/session OpenAgenda v2 et séance officialisée
   (texte visible ou JSON-LD, selon les preuves disponibles).
7. En sortie seuls des diagnostics *sans candidats, sans URL et sans secrets*
   peuvent être agrégés dans les logs des runners publics.

## Sécurité
- Aucun lien issu du lead ne peut devenir une épingle institutionnelle.
- Les URL externes, non HTTPS, sur IP et avec redirection par requête
  ne sont jamais sélectionnées.
- Les liens dans script/style ou éléments HTML masqués sont écartés.
- Plusieurs séances de même intitulé et même date avec URL distinctes
  restent ambiguës et en attente.
- Aucun `data-cal`, JavaScript ni horodatage n'est interprété comme droit
  d'admission.
- Les événements scolaires, annulés, adultes, passés ou sans preuve de
  séance restent refusés par les étapes indépendantes.
- `approval_granted=False`, `publisher_connected=False`,
  `public_writes=0` dans toutes les branches.

## Limites à ne pas masquer
- Ce routeur traite **les pages contenant les ancres EventON** décrites ;
  il ne traite pas les calendriers JavaScript sans HTML serveur, les
  calendriers d'autres éditeurs ou les flux RSS/Atom (PR dédiée #393).
- Le timestamp est une heuristique de sélection : il peut produire des
  faux négatifs si l'éditeur utilise un autre schéma, mais ne transforme
  pas un match en preuve de séance.
- L'identité de l'organisateur, les licences/droits, l'âge exact, les
  conditions d'inscription, la catégorie et l'historique demeurent des
  contrôles **distincts et non exécutés par le routeur**.
- Une preuve réelle sur un événement nécessite encore la récupération
  de l'index, de la page officielle, de l'API OpenAgenda et du géocodage,
  sous un compte d'exécution privé.

La PR reste **en brouillon**, sans intégration au publisher ni modification
de production, secrets, crons, GitHub Pages ou Infomaniak.
