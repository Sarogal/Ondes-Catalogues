# P'tites Ondes — preuve croisée d'une séance familiale MPT et de son lieu IGN

**17 novembre 2026 — PR empilée sur le pilote GPS #361, lecture seule, aucun publisher.**

## Contexte

- #350 fournit l'adaptateur de découverte nationale et le prévalidateur #346 demeure indépendant.
- #360 (brouillon séparé) sait parcourir 24 fiches des Maisons pour tous de Montpellier et en extrait 24 occurrences, dont 13 catégorisées pour revue.
- #361 (brouillon, base de cette PR) documente trois bâtiments MPT en croisant adresse municipale et IGN au **numéro de voie**.
- Le chantier actuel teste le **raccordement en lecture seule** avec #346 pour un seul cas officiel : [Bébés lecteurs, 18 novembre 2026 à 10 h 30, Maison pour tous Frida Kahlo](https://mpt.montpellier.fr/evenement/bebes-lecteurs).

Il **ne** représente **pas** une candidature de publication ni une admission. L'hôte institutionnel et le point IGN sont des entrées explicitement revues hors du collecteur. Le prévalidateur ne peut pas signer l'identité réelle des organisateurs.

## Séparation stricte des preuves

1. Le **candidat d'agenda** fournit une demande de preuve, jamais une preuve d'adresse ou de confiance.
2. Le **registre géographique statique distinct** fournit l'identité exacte du bâtiment et le point IGN ; on **recontrôle en direct** le résultat BAN `housenumber` (score ≥ 0,95, distance ≤ 15m, code postal et ville identiques). Le domaine géographique ne peut pas être fourni par le candidat.
3. La fiche **municipale effectivement relue** doit avoir un titre H1 visible correct et une **première section événement `<article>`** correspondante. Aucune date ni heure issue de la section « Autres événements » n'est admissible.
4. Une **date et son heure de début doivent figurer dans le même bloc de séance visible** (les balises cachées, scriptées et `aria-hidden` sont exclues).
5. L'article principal doit confirmer **le nom exact du bâtiment, son adresse de voie et son code postal**, concordants avec le registre géographique. Une adresse erronée malgré le bon nom est refusée.
6. La classification et le contrôle général indépendant #346 (âge déclaré, accès, public enfant, doublon contre le catalogue historique de 549 fiches) sont rejoués **sans modifier le catalogue**. Tout conflit d'accès, tel que « carte MPT obligatoire », conserve son statut bloquant.
7. Le résultat est un simple **compteur d'indices officiels prévalidés**, sans attestation cryptographique de l'organisateur, validation humaine, publication ou écriture de données.

## Points éditoriaux qui restent en attente

- La fiche « Bébés lecteurs » cite **la médiathèque Émile Zola comme organisateur** et la MPT Frida Kahlo comme partenaire ; il faut distinguer l'auteur de la manifestation du bâtiment où elle se déroule.
- « Dans la forêt » est une **installation artistique**, et non une excursion nature automatiquement déduite du mot « forêt ». Le pilote la place explicitement **en attente d'une classification éditoriale** si cette catégorie est suggérée.
- « Méli’Pitchouns » indique « Gratuit » ainsi qu'une **carte MPT obligatoire** ; sa situation ne peut pas être publiée comme un accès gratuit inconditionnel.
- Les conditions d'âge de la fiche « Bébés lecteurs » sont exprimées `0–3 ans`, mais le simple collecteur n'en construit **aucune borne d'âge numérique** : la preuve détaillée d'âge doit être traitée indépendamment avant admission.

## Protocole de tests

- `scripts/ptitesondes_mpt_family_independent_preflight.py` : vérification du premier article, géographie indépendante et agrégation anonyme, sans accès au publisher ou aux secrets.
- `tests/test_ptitesondes_mpt_family_independent_preflight.py` : fixtures entièrement fictives, couvrant fausse séance présente uniquement dans la barre latérale, date masquée, date inventée, faux domaine, mauvaise adresse, GPS déplacé, doublon déjà publié, accès ambigu, catégorie nature erronée et catalogue invalidé.
- `scripts/ptitesondes_mpt_source_geo_live_pilot.py` : une **seule séance officielle épinglée** (18/11/2026) et son adresse IGN ; collecte ponctuelle, aucune sauvegarde de candidat, source HTML et URL du candidat jamais affichées dans les journaux.
- Workflow GitHub Actions **public**, sur PR seulement pour la lecture réelle, `contents: read`, sans secret ni cron, avec échec bloquant si un indice de la source disparaît.

L'audit est daté du **17 novembre 2026**. Une séance passée ne constitue pas une nouvelle publication, et un succès technique au jour de l'audit ne prouve pas l'ouverture future ou les places disponibles.

**Aucune modification** de `sorties.json`, `lieux.json`, des conditions de publication, des sources historiques, des crons GitHub Actions existants, des secrets ou de la production Infomaniak. **Ne pas fusionner ni publier sans accord explicite.**
