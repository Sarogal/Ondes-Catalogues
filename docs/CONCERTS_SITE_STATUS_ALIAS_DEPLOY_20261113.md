# Grosses Ondes — corrections d'affichage des annulations et alias (13 novembre 2026)

## Ce qui est confirmé sur le site réel

- La recherche `Ramoneurs de Menhir` retrouve deux dates : 20 novembre 2026 (Le Bateau Ivre, Tours, confirmé) et 27 juin 2027 (Secret Place, Saint-Jean-de-Védas, ANNULÉ).
- L'annulation officielle est dans le catalogue public `concerts.json`, mais le badge porte encore la classe CSS `confirmed`.
- La liste « Prochains concerts » n'exclut pas les annulations par défaut.
- Le détail « Toutes les dates » recherche un seul ID d'artiste alors que `les-ramoneurs-de-menhir` et `les-ramoneurs-de-menhirs` désignent le même groupe.
- Les dates des en-têtes de l'agenda omettent l'année.

## Correctif prêt, déploiement non réalisé

Les fichiers Web réels sont hébergés sur Infomaniak : **le dépôt public GitHub ne publie pas le JavaScript du site**. Pour cette raison, cette PR n'effectue aucun déploiement ni écriture privée.

1. Télécharger les trois fichiers réellement servis par `https://grosses-ondes.fr/concerts/` depuis le gestionnaire de fichiers Infomaniak : `app.js`, `styles.css`, `index.html`. Conserver une copie de sauvegarde avant modification.
2. Depuis la racine du dépôt public, lancer :
   ```sh
   python scripts/concerts_site_status_patch.py --app /chemin/originaux/app.js --css /chemin/originaux/styles.css --index /chemin/originaux/index.html --out /chemin/nouveau-dossier-vide
   ```
3. Le préparateur vérifie **une occurrence exacte de chaque ancre** ; il échoue sans produire de fichiers si les originaux ont dérivé. Il refuse les doubles modifications et les dossiers de sortie non vides.
4. Comparer les deux versions et contrôler les substitutions prévues. Déployer **uniquement les 3 fichiers corrigés de la sortie** vers le dossier `concerts/` sur Infomaniak, sans modifier `catalogue.json`, les festivals ni les autres rubriques.
5. Tester réellement en navigation privée, après actualisation du cache :
   - par défaut, l'annulation n'est plus un « concert à venir » ni un marqueur de la carte ;
   - en cherchant `Ramoneurs de Menhir`, l'annulation reste consultable avec badge distinct `ANNULÉ` et lien source officielle, sans lien de billetterie ;
   - le 20 novembre 2026, Tours + Toxic Frogs reste confirmé ;
   - en cliquant sur l'un des deux alias, **les deux dates** sont visibles ; les festivals sont recoupés par les deux noms sans réécriture d'ID ;
   - l'année est visible dans les en-têtes et les compteurs/liste/carte sont cohérents ;
   - les autres artistes, salles et zones géographiques fonctionnent sans régression.
6. Si un contrôle échoue, restaurer immédiatement les originaux sauvegardés ; ne jamais laisser un concert annulé présenté comme confirmé.

## Règle de source et sécurité

- Ne pas modifier les 127 événements historiques, les approbations privées ou leurs preuves.
- L'alias est un **couple vérifié nominativement**, pas une heuristique générique retirant un « s » à tout artiste.
- Une PR verte ne confirme pas le déploiement Infomaniak. Ne déclarer l'affichage corrigé qu'après contrôle en navigateur des fichiers réellement servis.
