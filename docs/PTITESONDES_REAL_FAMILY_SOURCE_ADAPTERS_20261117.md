# P'tites Ondes — sources familiales réelles (17 novembre 2026)

**Brouillon — aucun merge, aucun déploiement et aucun changement de cron.**

## Référence vérifiée

- Dépôt public Sarogal/Ondes-Catalogues : catalogue version 3, 548 fiches, 7 catégories musicales, dernière MAJ 2026-11-16T19:48:51+01:00, blob SHA Git 22da43da4ff77b90158666017988f472bee591b9.
- Catalogue GitHub Pages réellement servi : 548 fiches, dont 363 commençant le 17/11/2026 ou après ; mêmes identifiants et métadonnées que le dépôt. Le lecteur d'audit transforme parfois les caractères '&' en '&amp;' : cela interdit d'affirmer l'identité octet par octet sur la base de cette lecture.
- Catalogue historique toujours en ligne sur https://ptitesondes.fr/config/sorties.json : 487 fiches, dernière MAJ 2026-10-22T21:00:00+02:00. Il reste intact.
- #342 (classification) et #346 (prévalidateur national) déjà intégrées à main. #347 v174 toujours en brouillon ; la chaîne municipale #335 → #337 → #341 reste non fusionnée.

## Sources réelles étudiées

| Source | Format et intérêt | Conditions et précautions |
|---|---|---|
| [Maisons pour tous Montpellier](https://mpt.montpellier.fr/evenements), [fiche Parcours motricité](https://mpt.montpellier.fr/evenement/parcours-motricite) | HTML municipal avec séances explicitement datées | Droits de réutilisation de l'HTML non homologués, collecte seulement ; aucune description ni image republiée |
| [Que Faire à Paris ?](https://opendata.paris.fr/explore/dataset/que-faire-a-paris-/) | API OpenDataSoft Explore v2.1, agenda officiel participatif, champ occurrences | **Licence ODbL** : attribution et obligations de partage à examiner avant publication ; recouper la source organisatrice |
| iCalendar (ICS) institutionnel | Adaptateur générique multi-collectivités | Aucun flux homologué pour le moment, sources et licences à examiner une par une |
| [Nantes Métropole](https://metropole.nantes.fr/que-faire-a-nantes/agenda/30879596_creation-dun-petit-court-metrage-amateur) | Fiches officielles HTML, parfois via OpenAgenda | Source évaluée ; éviter un scraper ad hoc si un flux commun suffit |
| [OpenAgenda API v2](https://developers.openagenda.com/) | Réseau national de flux structurés existant | Pipeline déjà actif, ne pas créer de doublon ; vérifier droits et URL canoniques de chaque annonce |
| [Agendas participatifs Occitanie](https://www.data.gouv.fr/datasets/agendas-participatifs-des-sorties-en-occitanie) | Répertoire agrégé régional | Licence Ouverte 2.0 ; source de découverte, pas une preuve de l'organisateur |

Exemple réel : la fiche MPT « Parcours motricité » affiche les 17 et 18 novembre 2026, puis les 20 janvier, 24 février et 21 avril 2027, de 10 h à 11 h, pour les 18 mois à 6 ans. La mention « Gratuit » coexiste avec une carte MPT obligatoire : l'adaptateur ne doit pas annoncer un accès gratuit sans condition et place le prix en état ambigu pour révision. Les cinq séances sont des **pistes** et non des fiches admises.

## Architecture et limites

Les adaptateurs isolés prennent en entrée un document, sans le télécharger eux-mêmes. Ils extraient les occurrences explicites et les URL de preuve ; ils refusent les événements annulés, les pages étrangères, les horaires absents, l'expansion des récurrences ICS et les plages de dates prises à tort pour des séances.

Le raccordement de forme au contrat #342 ne remplace pas #346 : ce prévalidateur exige sa propre liste d'organisateurs, la relecture des pages officielles, une géolocalisation vérifiée par un fournisseur indépendant, le contrôle des doublons et une empreinte de catalogue. Aucune coordonnée GPS n'est produite par les adaptateurs.

La chaîne d'autorité demeure : découverte → qualification → preuve indépendante → géolocalisation → anti-doublons → validation privée → admission → publication autorisée. Les variables obligatoires restent publication_ready=false, approval_granted_to_publisher=false et public_writes=0.

## Livrables de cette PR

- scripts/ptitesondes_real_family_source_adapters.py : adaptateurs Paris, Montpellier, ICS, bilan agrégé et propositions au contrat #342.
- scripts/ptitesondes_real_family_source_live_smoke.py : lecture **ponctuelle** de 100 enregistrements Paris au maximum et d'une fiche MPT ; sortie de compteurs anonymes uniquement ; gestion bornée du réseau.
- tests/test_ptitesondes_real_family_source_adapters.py : fixtures fictives et tests adversariaux, jamais des événements effectivement approuvés.
- .github/workflows/ptitesondes-real-family-source-adapters-tests.yml : tests sur runner public, permissions lecture seule, aucun secret, pas de cron.

**Aucune modification** des catalogues, du publisher, des scripts OpenAgenda existants, des horaires de veille, des dépôts privés, d'Infomaniak ni des moteurs Grosses Ondes.

## Suite requise

Valider les licences, les hôtes organisateurs et leurs identités ; homologuer des registres indépendants de lieux/GPS ; tester en conditions réelles l'accès API Paris et les pages MPT ; élargir à plusieurs fiches et collectivités sans dépasser les quotas ; effectuer l'anti-doublon ; réviser en privé les preuves et les décisions ; puis seulement préparer une publication soumise à autorisation.

**Cette PR ne demande ni fusion ni publication.**

## Validation réelle et diagnostics CI

- Première collecte ponctuelle : **36 occurrences candidates**, dont 31 Paris et 5 Montpellier ; 12 propositions thématiques structurées, aucune preuve GPS ni approbation privée.
- Un second passage sur 100 résultats Paris non triés a donné **89 occurrences**, dont 84 Paris et 5 Montpellier, 13 structurées : **cet écart ne traduit pas 53 nouvelles activités**, mais des échantillons API non épinglés. L'échantillonneur est maintenant trié par `date_start ASC, id ASC` ; ses prochaines mesures restent des fenêtres de 100 enregistrements, pas une estimation nationale.
- La prise en charge iCalendar reconnaît explicitement Europe/Paris, America/Guadeloupe, America/Martinique, America/Cayenne, Indian/Reunion et Indian/Mayotte. Le fuseau est un paramètre de source **homologuée indépendamment** : il ne se déduit pas du nom du lieu. Un événement en UTC est converti dans ce fuseau, jamais systématiquement en heure métropolitaine.
- Tests adversariaux spécialisés : CI publique `ptitesondes-real-family-source-adapters-tests.yml`, lecture seule, aucun secret.
- La **suite globale** peut échouer sur le test obsolète `test_real_branch_lacks_gosier_static_record_so_default_must_fail`, qui suppose #305 non fusionnée alors que le registre GPS a été intégré depuis. Ce problème est isolé dans la PR en brouillon **#352** ; ne pas masquer l'échec ni prétendre à une validation globale sans nouvel état GitHub Actions.
- Correctif indépendant de dédoublonnage des véritables séances individuelles préparé en **PR #351**. Les adaptateurs ici ne le déclenchent pas directement.
