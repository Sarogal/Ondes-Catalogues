# P'tites Ondes — Préparation isolée du raccordement municipal au synchroniseur

**16 novembre 2026 — DRAFT, aucun connecteur activé, aucune publication.**

## Dépendance

Branche empilée sur la PR publique **#334** (sur #332 → #330 → #328 → #325 → #323).
Les PR #305 (GPS homologué), #327 (prévisualisation carte v173),
#310 et #322 restent indépendantes. Les PR privées #64/#65/#66 sont intactes.

La PR ajoute un module `scripts/ptitesondes_municipal_sync_rehearsal.py`,
des tests et un workflow de tests public, **sans changer** le synchroniseur
`merge_policy.merge`, le promoteur OpenAgenda, le catalogue JSON,
la carte, les lieux permanents, les crons et Infomaniak.

## Ce que le modèle simule

1. Vérifie les deux SHA-256 exacts, la référence historique, le catalogue
   actuellement servi **fourni au contrôleur** et le préfixe append-only.
2. Exécute le contrôle #334 du lot, lequel relit les preuves municipales
   et les décisions privées authentifiées par occurrence, dont la décision
   éditoriale SOURCE_ONLY si le prix ou l'inscription restent inconnus.
3. Si une seule occurrence est refusée, **zéro ajout hypothétique**.
4. Si toutes passent, modélise chaque fiche de la catégorie autorisée
   uniquement dans une copie mémoire, en préservant l'ordre des fiches
   historiques, les nouveaux événements déjà présents et le champ `updated_at`.
5. Confirme que le synchroniseur public actuel **rejette toujours** les
   nouvelles catégories ; ne modifie pas sa liste d'acceptation.
6. Recontrôle le contenu et les SHA des deux catalogues en sortie.
7. Renvoie seulement des compteurs agrégés. Aucun `events`, `additions`,
   `patch.v1`, chemin de sortie ou ID privé n'est exposé.

### Limite de preuve volontaire

Le modèle exige des dates de contrôle source et GPS de moins de 14 jours,
mais ces dates sont **des entrées de planification non authentifiées** :
elles ne doivent **JAMAIS** devenir des dates de vérification publiables.
Une future procédure de publication doit obtenir une attestation indépendante
du contrôle GPS et de la source, liée cryptographiquement au dossier privé
et à son manifeste. L'existence d'un accord humain simulé dans les tests
ne dispense jamais de cette étape.

Une simulation concluante n'est **pas** une validation du contenu réel.
Les neuf jeux de données du test ont des identifiants et des conditions
d'accès **inventés exclusivement dans les fixtures**.
Les vraies séances du Gosier ont des tarifs/inscriptions non précisés
dans les observations du 16 novembre ; ne pas les présenter comme gratuites.
L'atelier CINOR de La Réunion reste sur la filière OpenAgenda, jamais
dans cette voie municipale du Gosier.

## Tests

`python -m unittest discover -s tests -p 'test_ptitesondes_municipal_sync_rehearsal.py' -v`

Le workflow dédié n'utilise **aucun secret**, aucune écriture GitHub,
aucun job programmé et aucune donnée privée réelle.

Cas couverts : lot neuf séances / calendrier historique intact / production
non appelée / jeton absent / refus de toute publication partielle /
conditions inconnues non approuvées / contrôles périmés / approbation
sur ancien SHA / doublon de dossier / erreur GPS / page municipale modifiée /
erreur de SHA / changement des événements historiques / absence de patch.

## Conditions avant un vrai raccordement

- Validation indépendante du registre GPS et de l'interface v173.
- Source municipale et géolocalisation contrôlées **à nouveau** avec
  preuves horodatées et authentifiées, indépendamment de toute entrée
  déclarative du collecteur.
- Accord par occurrence et accord éditorial distinct si nécessaire ;
  révocation et changement de SHA doivent invalider la publication.
- Contrat de prévalidation publique dédié, dans un nouveau module
  indépendante de la politique OpenAgenda, avec tests adversariaux.
- Confrontation à la version publique en ligne au moment de l'insertion ;
  copie / restauration et procédure de retour arrière approuvées.
- Autorisation expresse pour toute fusion de PR, mise à jour de catalogue
  ou déploiement Infomaniak.

**États de sortie invariants :** `publication_ready=false`,
`approval_granted_to_publisher=false`, `public_writes=0`,
`municipal_publisher_not_connected=true`.

## Retour arrière

Fermer la PR et supprimer sa branche sans modifier la production.
Aucun rollback du catalogue n'est nécessaire : aucune écriture publique.
