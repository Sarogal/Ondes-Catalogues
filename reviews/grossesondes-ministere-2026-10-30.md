# Grosses Ondes — découverte à partir de la base ministérielle (30 octobre 2026)

## Mise en service de l'historique (lot 2, 30 octobre 2026)

- **3 archives métal / hard rock approuvées** : Rock In Bourlon, Heavy Metal Breizh et Bully on Rocks. L'historique GitHub Pages passera de **170 à 173 références** après succès des tests et du déploiement.
- **1 festival différé** : Festival de la Mer (Landunvez), principalement punk/hardcore/rock alternatif, conservé dans le registre de candidats sans publication.
- Le calendrier de **124 éditions reste inchangé**.
- La photographie initiale Infomaniak demeure à **170 archives** et son empreinte SHA-256 est conservée. Seule l'extension autorisée, contrôlée entrée par entrée et en ordre, est admise par la prévisualisation et le synchroniseur.
- Le nouveau workflow GitHub Actions exécute **tous les tests**, vérifie la photographie publique et ne déploie sur Pages que si l'ensemble est conforme. Il n'écrit jamais sur Infomaniak.
- Aucun calendrier futur, date 2027 ou point de carte n'est créé à partir des archives.

## Portée du lot

Source : [Liste des festivals en France — ministère de la Culture](https://www.data.gouv.fr/datasets/liste-des-festivals-en-france), Licence Ouverte 2.0. CSV utilisateur de 7 283 lignes, recensement de référence 2019 ; la mise à jour technique du fichier en septembre 2026 ne valide aucune édition 2026/2027.

Référence de départ : `docs/grossesondes/festivals.json` (124 éditions, 30/10/2026) et `docs/grossesondes/festival-history.json` (170 références, 22/10/2026).

## Quatre fiches **historiques** conservées dans un lot candidat distinct

| Festival | Dernière édition documentée | Sources | Remarque |
|---|---|---|---|
| Rock In Bourlon (62) | 26–28 juin 2026 | [Association](https://www.helloasso.com/associations/rock-in-bourlon/evenements/rock-in-bourlon-2026), [site officiel](https://www.rockinbourlon.com/about-1) | Musiques lourdes |
| Heavy Metal Breizh (56) | 24 janvier 2026 | [Mairie de Pluméliau-Bieuzy](https://www.plumeliau-bieuzy.bzh/agenda/heavy-metal-breizh-2/) | 9 groupes ; noms non extrapolés |
| Bully on Rocks (62) | 29–30 mai 2026 | [Ville de Bully-les-Mines](https://www.bullylesmines.fr/actualite/bully-on-rocks-le-rendez-vous-incontournable-revient-pour-deux-jours/) | Ne pas confondre avec le rendez-vous distinct du 17 octobre |
| Festival de la Mer (29) | 24–25 juillet 2026 | [Organisateur](https://festivaldelamer.com/), [commune](https://landunvez.fr/evenements/concerts-festival-de-la-mer/) | **Genres voisins** : punk / hardcore / rock alternatif, pas exclusivement métal |

Les **170 entrées existantes** sont conservées **sans aucune modification du JSON public**. Les quatre fiches prêtes à intégrer sont isolées dans `reviews/grossesondes-historical-candidates-2026-10-30.json` : après préparation et avant publication éventuelle, l'historique aurait **174 références**. Cette séparation évite de bloquer le synchroniseur actuel, qui exige encore une concordance immuable des 170 archives avec sa référence Infomaniak. Aucune date 2027 n'est inventée. Le festival de la Mer doit être validé éditorialement si la carte se limite aux festivals strictement métal.

## Huit autres références documentées — vérification avant toute intégration

| Candidat | Dernière preuve identifiée | Décision à ce stade |
|---|---|---|
| Nantes Metal Fest (44) | [7–9 décembre 2023, HARD FORCE](https://hardforce.com/actu/42155/nantes-metal-fest-2023-onzieme-edition-7-8-9-decembre-ferrailleur) | Historique possible ; association indiquée dissoute en février 2024, ne pas annoncer un retour |
| Keudfest (53) | [5–6 juillet 2024, organisation](https://keudfest.jimdosite.com/) | Vérifier programmation métal avant classement |
| The Outbreak Metal Fest (41) | [10, 12 et 13 avril 2019, reportage Metal Obs](https://metalobs.com/live-report-the-outbreak-metal-fest/) | Historique métal recevable ; événement multi-lieux, aucune édition future |
| OUTCH! Extreme Metal Festival (52) | [Archive 2018–2020, Route des Festivals](https://www.routedesfestivals.com/en/festival/outch-extreme-metal-festival-12055) | Dates et tenue effective à recouper |
| Liévin Metal Fest (62) | [15 mars **2024**, programme ILLICO! (p.62)](https://illicomag.fr/pdf/74-illico.pdf) ; [2023, mairie](https://lievin.fr/lievin-terre-de-metal) | **Corriger 2023 → 2024** dans l'audit ; aucune prochaine édition confirmée |
| Fest Hom Fred (80) | [2019, archive de concert](https://france-metal-museum.fr/bootlegs.htm) ; [2017, La Grosse Radio](https://www.lagrosseradio.com/webzine-metal/p71752-festival-fest-hom-fred-v-21-10-2017/) | Historique possible, preuve 2019 indirecte |
| Rock'Aisne (02) | [12–13 mai 2023, annonce](https://www.eterritoire.fr/evenements/france%2Chauts-de-france%2Caisne%2Cchauny/) | Festival rock multigenre ; décision éditoriale requise |
| Metalgresifest (38) | [26 mai 2018, presse locale](https://www.ledauphine.com/isere-sud/2018/05/30/des-concerts-de-qualite-a-metalgresifest) | Historique métal recevable ; prochaine édition inconnue |

**Hors périmètre** : Rock en Maine (44) reste une option à arbitrer pour le punk rock.

## Prototype d'automatisation

- `scripts/grossesondes_ministere_discovery.py` lit la ressource ministérielle, compare noms / variantes et départements aux deux JSON, et produit un rapport de candidats en **lecture seule**.
- `.github/workflows/grossesondes-ministere-discovery.yml` prévoit une exécution **mensuelle**, ainsi qu'un déclenchement manuel ; l'artefact est un rapport à contrôler. Aucun changement du catalogue ni déploiement.
- `tests/test_grosses_ministere_discovery.py` vérifie notamment les doubles BOM CSV, la détection des doublons, les codes INSEE et l'absence systématique de date future confirmée.
- Si le téléchargement CSV officiel échoue, la tâche **échoue sans publier** quoi que ce soit.
- Le rapprochement automatique est volontairement conservateur et peut produire des faux positifs / faux négatifs. La publication de nouvelles fiches continue d'exiger une recherche officielle indépendante et la validation du lot.

## À vérifier avant fusion

1. **Migration préparée sur une branche isolée** : n'autoriser que les trois archives approuvées en append-only ; ne pas inclure Festival de la Mer sans validation éditoriale distincte.
2. Exécuter les tests du dépôt et tester le téléchargement depuis GitHub Actions (premier job GitHub Actions `41122527701` passé).
3. Revoir le lot de 8 archives et les 14 autres pistes incertaines dans le rapport initial.
4. Vérifier que la fusion n'active pas de modification de `festivals.json` ni de publication implicite : les workflows actuels font des synchronisations distinctes.
5. Déployer les trois archives historiques sur GitHub Pages uniquement après réussite des tests et du contrôle des deux sources publiques ; ne pas modifier Infomaniak.

**Aucune modification du site en production dans ce lot.**
