# P’tites Ondes — premier registre géographique familial indépendant (Montpellier)

**17 novembre 2026 — dossier de revue isolé, trois lieux, aucune sortie autorisée.**

## Pourquoi ce chantier

La PR #360 découvre désormais des occurrences de l'[agenda municipal Maisons pour tous](https://mpt.montpellier.fr/evenements), mais ces découvertes ne donnent ni une latitude/longitude homologuée ni une preuve d'accès grand public. La chaîne nationale #346 refuse à juste titre un lieu non documenté.

Ce lot prépare **trois identités de bâtiments**, avec adresse municipale publiée et point géographique de numéro de voie indépendant de l'IGN. Il ne modifie aucun catalogue, n'ajoute aucun lieu à la carte et n'accorde aucune attestation humaine.

## Preuves et concordance relevées

| Lieu exact | Adresse constatée sur la fiche municipale | Point IGN/BAN confirmé (latitude, longitude) | Score / type |
|---|---|---|---|
| Maison pour tous Mélina Mercouri | 842 rue de la Vieille Poste, 34000 Montpellier | 43.614655, 3.907746 | 0.9769 / housenumber |
| Maison pour tous Frida Kahlo | 240 rue Claude Lévi-Strauss, 34000 Montpellier | 43.595814, 3.903417 | 0.9725 / housenumber |
| Maison pour tous Albert Dubout | 2 rue des Tourterelles, 34090 Montpellier | 43.626242, 3.879302 | 0.9704 / housenumber |

**Sources municipales de nom et d'adresse :**
- [Méli’Pitchouns — MPT Mélina Mercouri](https://mpt.montpellier.fr/evenement/melipitchouns-atelier-deveil-et-de-lecture).
- [Bébés lecteurs — MPT Frida Kahlo](https://mpt.montpellier.fr/evenement/bebes-lecteurs).
- [Dans la forêt — MPT Albert Dubout](https://mpt.montpellier.fr/evenement/dans-la-foret).

**Points géographiques indépendants :**
- [IGN, 842 rue de la Vieille Poste](https://data.geopf.fr/geocodage/search?q=842%20Rue%20de%20la%20Vieille%20Poste%2034000%20Montpellier&limit=2)
- [IGN, 240 rue Claude Lévi-Strauss](https://data.geopf.fr/geocodage/search?q=240%20Rue%20Claude%20Levi-Strauss%2034000%20Montpellier&limit=2)
- [IGN, 2 rue des Tourterelles](https://data.geopf.fr/geocodage/search?q=2%20Rue%20des%20Tourterelles%2034090%20Montpellier&limit=2)

Les trois résultats présentés le 17/11/2026 correspondent à des numéros de voie (`type=housenumber`) et non à des centroïdes de rue. La position d'un numéro reste une approximation de l'accès réel au bâtiment : toute divergence d'événement reste vérifiée séparément et soumise à la tolérance légitime de la chaîne nationale (65 m).

## Contrats techniques

- `scripts/ptitesondes_mpt_independent_geo_pilot.py` : registre de trois adresses **épinglées**. Contrôle strict ville, nom, département, domaine institutionnel `mpt.montpellier.fr`, domaine géographique `data.geopf.fr`, code postal et score **≥ 0,95**. Une vérification live doit confirmer un géocodage `housenumber` à **15 mètres maximum** du point épinglé.
- `national_preflight_venue_registry()` : donne uniquement les neuf champs de la référence géographique que le prévalidateur #346 sait recevoir, **sans créer de paquet de preuve d'événement**.
- `review_exact_venue_name` : identité exacte avec nom et ville ; aucun alias automatique, aucun GPS déduit d'un nom de ville.
- `scripts/ptitesondes_mpt_geo_live_smoke.py` : interroge ponctuellement uniquement les trois requêtes IGN épinglées, sans redirection ni secret, affiche des **compteurs anonymes** et signale une source indisponible au lieu de la considérer vérifiée.
- `tests/test_ptitesondes_mpt_independent_geo_pilot.py` : tests hors réseau, cas adversariaux de faux domaine, mauvais code postal, mauvais numéro, géolocalisation déplacée, doublon, score bas, ambiguïté de lieu et absence de publication.

## Frontières à ne pas franchir

Le registre **ne doit pas** être pris pour une autorisation de publication. Les séances individuelles exigent :
1. **Date et heure exactes** recontrôlées sur la fiche et dans le même bloc visible ; aucune expansion de récurrence.
2. **Organisateur et audience enfants** indépendamment examinés. « Bébés lecteurs » cite notamment la médiathèque Émile Zola comme organisateur et Frida Kahlo comme partenaire : il ne faut pas confondre lieu et auteur.
3. **Conditions d'accès** : « Méli’Pitchouns » affiche « Gratuit » et « Carte MPT obligatoire », qui reste **ambigu** pour un accès sans frais.
4. **Classification éditoriale** : « Dans la forêt » est une installation artistique en intérieur et ne doit **pas** être automatiquement considérée comme une sortie nature à cause du mot « forêt ».
5. **Coordonnées du programme et absence de doublon** : les trois points référencés ne sont que des bâtiments, pas une certitude sur chaque activité future.
6. **Accord privé et chaîne publisher** : restent indépendants et inchangés.

Aucune catégorie musicale historique, règle OpenAgenda, cron, secret, dépôt privé, publication GitHub Pages, `sorties.json`, `lieux.json` ou déploiement Infomaniak n'est modifié.

## Séquence envisagée

Après validation du contrôle live et des tests généraux, une PR séparée pourra connecter les nouvelles découvertes MPT et ce registre à une **prévalidation indépendante en lecture seule**, qui conservera ses propres preuves de source/organisateur, le contrôle des doublons et les décisions privées. **Aucune activation de publisher n'est incluse dans ce lot.**

**Ne pas fusionner ni publier sans accord explicite.**
