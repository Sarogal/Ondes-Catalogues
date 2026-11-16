# P'tites Ondes — Attestation privée liée aux preuves municipales et au lieu GPS

**16 novembre 2026 — DRAFT, diagnostic exclusivement. AUCUNE publication activée.**

## Branche et dépendances

Nouvelle branche empilée sur la PR **#335** puis **#334 → #332 → #330 → #328 → #325 → #323**.
Les PR distinctes **#305** (lieux GPS Guadeloupe/Réunion), **#327** (carte v173),
**#310/#322** (veille ultramarine), et privées **#64/#65/#66** restent non fusionnées.
Aucune opération Infomaniak.

Le programme `scripts/ptitesondes_municipal_source_geo_attestation.py`
n'est ni importé ni appelé par `merge_policy.merge`, la veille OpenAgenda,
la publication des catalogues, ni par un workflow programmé. Il n'écrit rien.

## Objet : une troisième décision privée, pas une signature inventée

Les contrôleurs précédents #332 et #334 vérifient les fiches municipales, les
calendriers et l'approbation privée par occurrence. Lorsqu'une information
d'accès n'est pas indiquée, la décision privée distincte `SOURCE_ONLY`
reste obligatoire pour proposer seulement « Voir conditions ».

Ce nouveau module ajoute **une troisième attestation explicite** :
le propriétaire du dépôt privé doit commenter sur **la PR privée concernée**
une ligne exacte, vérifiable :

`PTITESONDES-MUNICIPAL-SOURCE-GEO-ATTEST-V1 <review_id> <sha256(receipt)> <head_sha>`

La révocation est :

`PTITESONDES-MUNICIPAL-SOURCE-GEO-REVOKE-V1 <review_id> <sha256(receipt)> <head_sha>`

**Ne pas saisir ces lignes pour de vraies séances maintenant.** Cette
nouvelle étape n'est pas connectée à une publication et les dossiers privés
réels ne disposent pas encore des attestations GPS finalisées.

L'empreinte SHA-256 du reçu lie :
- l'identité exacte de l'occurrence municipale ;
- la PR privée et son SHA courant, le manifeste, les objets candidat et accès ;
- l'empreinte exacte du catalogue au moment de la décision ;
- les octets UTF-8 de la fiche officielle municipale et du calendrier officiel
  du **jour concerné**, relus en HTTPS indépendamment du collecteur ;
- l'entrée exacte de la liste statique des lieux GPS validés :
  identité ville/lieu, point à 65 mètres maximum, URL institutionnelle
  et URL géographique sur **deux domaines distincts**.

**Important :** SHA-256 garantit ici l'égalité des octets, **pas**
l'authenticité de leur auteur. C'est l'API GitHub privée qui vérifie
l'auteur `Sarogal`, son rôle `OWNER`, ses droits administrateur/mainteneur,
l'état ouvert de la PR privée et le SHA de sa branche. Le commentaire le plus
récent, identifié par ID GitHub, prévaut ; une révocation invalide l'attestation.
Le champ `created_at` renvoyé par GitHub doit être au format UTC et dater de
**14 jours au maximum**, sans date future. Un commentaire sans date valide
ne constitue pas une attestation.

## Contrôles réels et limites

Le module rappelle la validation précédente #332 : date, heures, âge,
organisateur, annulation, accès, duplications, catégorie et vérification GPS.
Les deux lectures HTML sont mutualisées entre les vérifications pour ne pas
utiliser deux versions différentes de la même page dans le même audit.

**Le fournisseur géographique indépendant n'est pas recontacté** par ce
contrôleur : l'entrée homologuée du registre fait l'objet d'une comparaison
d'empreinte et de provenance, mais la pérennité réelle du point OSM/BnF reste
à vérifier dans la procédure finale de publication.

Par ailleurs, l'actuelle branche #335 ne contient **pas** encore les
nouveaux lieux de #305. Le parcours réel est donc refusé tant que cette
dépendance n'est pas validée et fusionnée suivant l'autorisation du propriétaire.
Des lieux « fictivement injectés » dans les tests sont uniquement des
doubles de test : ils ne créent aucune certification géographique.

La sortie ne contient **que des booléens et des motifs** :
`authenticated_private_attestation_passed` n'est jamais équivalent à
`publication_ready`, qui reste toujours **false**.
Le résultat ne contient ni événement, ni identifiant de dossier, ni source
privée, ni patch, ni clé, ni nouvelle liste de fiches.

## Tests publics, sans secrets

`python -m unittest discover -s tests -p 'test_ptitesondes_municipal_source_geo_attestation.py' -v`

Le workflow public n'utilise aucune clé privée ; il simule les réponses GitHub
et les pages officielles. La suite vérifie :
- le consentement distinct et la révocation ;
- l'auteur falsifié, les droits insuffisants, le SHA de PR modifié ;
- la date GitHub manquante, future ou périmée ;
- les empreintes de calendrier, fiche, GPS et catalogue liées au reçu ;
- l'absence de l'approbation ordinaire ou de `SOURCE_ONLY` ;
- les sources municipales altérées, les coordonnées incompatibles, les
  fournisseurs GPS sur le même domaine ou non HTTPS ;
- l'absence de registre Gosier réel sur la branche actuelle ;
- l'impossibilité de lancer un publieur ou d'émettre des ajouts.

## Restant avant déploiement, **aucune étape automatiquement autorisée**

1. Auditer et valider séparément le registre GPS #305, la carte v173 #327
   et les collectes ultramarines, en préservant la métropole et la Corse.
2. Préparer les vrais dossiers privés (un manifeste par occurrence), lire
   les conditions d'accès exactes et vérifier les preuves externes de
   coordonnées sur les sites institutionnels et OSM/BnF.
3. Évaluer une **nouvelle PR séparée** de raccordement du moteur #335
   à ce troisième contrôle, en exigeant un reçu authentifié pour **chaque**
   occurrence avant toute modélisation d'ajout.
4. Réévaluer l'actualité des événements (les séances passées sont exclues)
   et l'état du catalogue réellement servi juste avant toute proposition.
5. Demander explicitement l'autorisation avant chaque fusion, avant la
   première insertion dans le catalogue public, et avant Infomaniak.

## Retour arrière

Fermer la PR de préparation, sans restauration nécessaire : aucune modification
des fiches, du synchroniseur, de la carte ni des automatisations planifiées.
