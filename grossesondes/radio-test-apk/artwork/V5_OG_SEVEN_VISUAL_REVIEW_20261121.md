# Grosses Ondes — revue des nouvelles images sociales de 53 radios sans association v5

**21 novembre 2026. Qualification éditoriale limitée au TEST : aucune image signée ou activée.**

## Preuves reproduites

- [Découverte officielle en 8 lots](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44931329398) : **53** UUID historiques, **23** pages avec références image, **58** références, dont beaucoup de favicons génériques.
- [Contrôle SHA et décodeur](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44931636306) : **12** images sociales examinées, **9** images techniquement valides, **8** d'au moins 192 × 192.
- [Planche-contact SHA recontrôlée](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44931872556) : **7** prévisualisations correspondant à leurs preuves SHA précédentes ; RSTLSS avait deux URLs fournissant les mêmes octets.

Les visuels ont été observés sur la planche-contact à SHA verrouillé. Cette analyse est **une qualification visuelle de pistes**, pas une approbation automatique de nouvelles signatures.

## Décisions station par station

| Station | Revue d'image | Historique V64 | Décision |
|---|---|---|---|
| **Código Metal Radio** | 447×447, nom « Código Metal » explicite | Aucune URL | **Éligible à un futur aperçu unsigned** après contrôle de la fiche officielle ; bonne forme carrée |
| **Nuclear Fallout Radio** | 1600×460, nom station clairement présent | Aucune URL | **Fiche identifiée**, mais très large pour Android Auto ; chercher un équivalent carré avant de le privilégier |
| **BOLLOCKS Rock & Metal Radio** | 1672×804, nom entier visible | Ancien favicon Jimdo | Source officielle identifiable, **mais le planner TEST conserve déjà l'ancien logo** ; amélioration non destructive à développer |
| **RSTLSS** | 1200×630, « RSTLSS.COM » et mention radio | Ancien favicon RSTLSS | Source officielle identifiable, **mais ancien logo prioritaire dans le planner** |
| **181.FM - 80's HairBand** | 1200×630, simple marque « 181.fm » | Aucune URL | **NON APPROUVÉE pour le canal précis** : logo de réseau sans mention 80's HairBand |
| **Begoodradio.com 80s metal** | 1200×630, marque « Be Good Radio » | Aucune URL | **NON APPROUVÉE pour 80s metal** : marque générale sans identité du sous-programme |
| **Rock Radio Hard & Heavy SLO** | 1200×630, marque « Rock Radio » | Ancien logo réseau | **EN ATTENTE** : identité Hard & Heavy SLO non démontrée par ce seul visuel |

L'image de **Heavy Metal History Radio** est techniquement valide mais mesure seulement **144×144**, donc reste exclue du seuil 192px. Les images OG de Megarock Radio étaient indisponibles et Metal Heads a échoué au contrôle des octets ; aucune image n'est inventée.

## Source officielle vérifiée

- [Código Metal Radio](https://www.codigometal.cl/) : station de metal chilien 24/7, mot-symbole présent sur la vignette d'origine.
- [Nuclear Fallout Radio](https://www.nuclearfalloutradio.com/) : station officielle rock/metal, nom visible sur la bannière.
- [BOLLOCKS Rock & Metal Radio](https://www.bollocksradio.com/) : site officiel et visuel nominatif, dont la référence provient des métadonnées de sa page historique.
- [RSTLSS](https://rstlss.com/radioweb) : la station est identifiée comme une radio en direct, distincte des podcasts et des articles.

## Protection Flutter identifiée

`lib/services/central_artwork_sidecar_planner.dart` ignore **toute association** lorsqu'une station possède déjà `station.logoUrl` ou `station.catalogLogoUrl`. Ainsi, ajouter naïvement BOLLOCKS/RSTLSS au sidecar actuel n'améliorerait rien ; cela masquerait seulement un manque de logique de migration. Toute amélioration future devra conserver le cache et les UUID historiques et pouvoir revenir à l'ancien visuel si le nouveau n'est pas vérifiable.

La génération radio TEST reste **4**. `artwork/current.json` reste absent. Aucun manifest signé, APK, favori, flux ou publication Play Store n'est affecté.
