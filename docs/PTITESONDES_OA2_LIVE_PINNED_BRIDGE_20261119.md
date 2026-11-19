# P’tites Ondes — pont de lecture réelle vers OpenAgenda v2

**19 novembre 2026 — développement isolé sur PR empilée ; aucun raccordement au publisher.**

## Problème confirmé

La PR #399 et le recensement #408 préparent des preuves de provenance, mais
un `trusted_api_context` construit à partir d'un candidat, d'OpenDataSoft ou
d'un résultat d'API déjà présent dans le backlog ne prouve pas quelle requête
HTTP a effectivement été exécutée.

Le lecteur `read_direct_v2` existait déjà avec GET exact, HTTPS, absence
de redirection, statut 200, borne en octets et clé **publique** en en-tête.
Le nouveau module `scripts/ptitesondes_oa2_live_pinned_bridge.py` raccorde
ce transport au contrôle de la page institutionnelle de #399.

## Circuit de confiance, strict et générique

1. **Le caller privé** fournit une liste de cinq champs par institution :
   `institution_host`, `exact_page_url`, `agenda_slug`, `agenda_uid`,
   `timezone`. Elle doit être examinée en dehors du candidat.
2. Le candidat est seulement une **piste** : URL OA avec UID strict, ou
   ancien miroir `opendatasoft-index` à slug seul + UID séparé. Un format
   inconnu, un UID contradictoire ou un doublon de source enregistré est bloqué.
3. `fetch_official_page` récupère par GET HTTPS exact, sans redirection, la
   page institutionnelle déjà épinglée. Aucun lien du candidat ne peut choisir
   cette URL.
4. `inspect_institutional_agenda_page` exige un lien HTML visible vers
   la **racine exacte** de l'agenda OA attendu.
5. `read_direct_v2` exécute le GET événement vers
   `/v2/agendas/{agenda_uid}/events/{event_uid}` : URL construite
   exclusivement à partir de l'institution épinglée et de l'UID de piste.
   Le transport vérifie qu'il a reçu la réponse exacte sans redirection.
6. L'UID de réponse, le titre, la commune et le nom du lieu doivent être
   concordants. Le cas ODS ancien passe en plus par le diagnostic de #399,
   avec un reçu de requête créé **après** le retour du vrai lecteur.
7. Le résultat ne peut être que
   `strict_api_identity_bound_other_gates_pending`,
   `legacy_api_identity_bound_other_gates_pending` ou un code de refus fixe.

Le résultat **ne contient jamais** URL, titre, UID, coordonnées, réponse
HTTP brute, exception réseau ou clé. La clé n'est jamais placée dans l'URL.

## Frontières de sécurité et de preuve

Une page institutionnelle qui référence OpenAgenda ne prouve **pas**
l'identité juridique de l'administrateur de l'agenda ; un GET exact v2 ne
prouve **pas** l'origine institutionnelle d'une séance.

Les résultats positifs ne satisfont **aucune** des portes suivantes :
propriété institutionnelle indépendamment attestée, preuve de séance,
lieu/GPS vérifiés, âge et conditions d'accès, droits de reproduction,
déduplication historique, admission privée, publisher, visibilité publique.

Les `institution_opener` / `api_opener` facultatifs servent à injecter
des réponses fictives uniquement dans les tests unitaires. Un appel de
production en environnement de confiance doit utiliser les lecteurs réels
sans les remplacer et ne doit jamais journaliser le corps des événements.

**Aucun registre de sources réelles n'est inventé ou homologué dans cette PR.**
La dernière collecte privée examinée (19 novembre) avait 16 agendas API
interrogés, mais zéro propriétaire indépendamment attesté et zéro séance
indépendante démontrée : cette PR ne change pas ces chiffres.

## Tests / activation

Tests adversariaux : parcours UID strict, miroir ODS, registre absent,
registre ambigu, URL usurpée, lien masqué, redirections, HTTP non 200,
clé privée, faux UID, titre et lieu divergents, anonymisation.

La CI de diagnostic est uniquement `pull_request` avec
`permissions: contents: read`, sans cron, secrets ou déploiement. Aucun
workflow de production et aucun fichier de catalogue ne sont modifiés.

**Avant une future mise en service**, il restera à construire un registre
national officiellement vérifié, puis à raccorder les résultats aux
contrôles géographiques et de séances dans le moteur privé. La mise en
service doit être explicitement autorisée et testée sans écriture publique.
