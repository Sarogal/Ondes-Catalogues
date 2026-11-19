# P’tites Ondes — diagnostic de bout en bout index HTML → fiches → séances

**19 novembre 2026 — composant de démonstration, sans activation ni écriture.**

## Pourquoi ce pilote

La PR #420 permet de **repérer** des URL de fiches enfants depuis un index
HTML officiel. Ce fait seul n'établit aucune séance, aucun public enfant ni
aucune capacité de publier. La nouvelle PR développe le raccordement
générique à un **parseur de fiches existant** et à l'audit national des
propositions de sorties, avec métriques étape par étape.

Le site pilote est `mpt.montpellier.fr` (Maisons pour Tous de Montpellier),
dont le parseur de fiches `parse_montpellier_mpt_detail` préexistait dans le
projet. Nous n'ajoutons **aucune exception par événement**.

## Chaîne de lecture seule

1. Un caller de confiance sélectionne un index institutionnel **séparément
   des événements candidats** : hôte exact + URL HTTPS exacte.
2. `discover_live_html_event_pages` vérifie la page, ses liens visibles
   et leurs hôtes (PR #420).
3. Un contrat d'**adaptateur par famille de site**, non par événement,
   restreint les cibles à `/evenement/` sur le domaine revu.
4. Jusqu'à 12 fiches par défaut (maximum 30) sont relues par GET HTTPS
   exact sans redirection. Le résultat est un échantillon déterministe,
   avec nombre de fiches non inspectées indiqué.
5. Le parseur préexistant n'extrait que les séances futures explicites :
   titre, lieu déclaré, date et heure, catégorie familiale et état d'accès
   quand celui-ci est identifiable. Une plage de dates ne crée pas
   artificiellement une séance quotidienne.
6. `scope_proposals` mesure les propositions **structurellement plausibles**
   suivant les catégories et les refus de l'audit national.

La réponse publique est **purement agrégée** : liens, fiches tentées,
fiches lues/refusées, séances futures repérées, propositions plausibles,
raisons de refus à clés fixes. Aucune URL, titre, UID, adresse ni contenu de
page ne peut y être injecté.

## Niveau de confiance

**Interdit de confondre** :
- un lien repéré avec un événement confirmé ;
- une séance lue sur une page avec une séance admise ;
- un public enfant déclaré avec une plage d'âge indépendante validée ;
- un lieu nommé avec un point GPS indépendant vérifié ;
- un domaine institutionnel avec une licence de reproduction.

Les compteurs de GPS vérifié, de droits, de source authentifiée,
d'autorisation de publier et d'écriture publique restent à zéro ou faux.
Le diagnostic ne possède aucun connecteur vers le publisher ou les catalogues.

## Validation

11 tests hors réseau couvrent : index vers fiche vers date explicite,
plusieurs événements du même index, plusieurs séances sur une seule page,
adultes, annulation, date expirée, lieu manquant, host forgé, réponse enfant
indisponible, échantillonnage borné et anonymisation d'un rapport malveillant.

Les tests CI valident un **jeu de fixtures**, pas un recensement en
production. Le contrôle manuel des liens réels effectué précédemment a
repéré 24 URL distinctes de fiches sur l'index officiel des Maisons pour
Tous, mais la PR ne revendique ni 24 fiches réellement analysées ni
une nouvelle sortie publiée.

**Étape suivante** : exécuter le diagnostic depuis un environnement privé
de confiance sur des index officiellement revus, puis compléter les
preuves indépendantes de séance/âge/lieu/droits et les règles
anti-doublons. Rien ne doit être activé en production sans validation.
