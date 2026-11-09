# Ondes — surveillance indépendante des passages programmés

Le script monitoring/ondes_watchdog.php est un contrôleur **en lecture seule** du dépôt public Sarogal/Ondes-Catalogues. Il n'utilise aucun token privé et ne modifie ni intake, ni fiches, ni catalogues. Il vérifie via l'API GitHub les créneaux des collectes et synchronisations réellement exécutés avec succès, puis le schéma et les volumes minimum des quatre JSON servis par GitHub Pages.

Le contrôle examine les créneaux prévus sur les dernières 27 heures, en laissant **9 heures** de marge pour les retards potentiellement très importants. Une exécution manuelle ne remplace pas un déclenchement programmé. **Attention :** GitHub n'expose pas l'horaire cron exact dans la liste des runs ; l'association entre un passage prévu et une exécution très retardée est indicative. Les alertes de créneau doivent donc être vérifiées avec l'historique des runs et le résultat des jobs, et non interprétées comme une preuve absolue d'absence. Ce contrôle ne garantit pas la découverte de toutes les dates et ne compare pas le JSON public au dépôt main : cela appartient à la PR de réconciliation Pages #135.

## Contrôles locaux et GitHub

Tests : php -l monitoring/ondes_watchdog.php ; php monitoring/ondes_watchdog.php --self-test.

Le workflow en lecture seule ondes-public-watchdog.yml se lance deux fois par jour et peut être lancé manuellement. Il peut lui-même manquer lors d'une panne GitHub : il ne remplace pas la surveillance indépendante.

## Installer la surveillance indépendante chez Infomaniak

1. Déposer monitoring/ondes_watchdog.php dans un dossier PHP dédié de l'hébergement (PHP 8 ou plus). Ne pas importer de données privées.
2. Si le planificateur appelle une URL HTTP, créer à côté du script un fichier non versionné **ondes-watchdog.local.php** contenant une seule instruction PHP retournant un secret aléatoire d'au moins 32 caractères, par exemple : <?php return 'REMPLACER_PAR_UN_SECRET_ALEATOIRE_LONG'; . Ne jamais utiliser un token GitHub comme secret du watchdog.
3. Dans le Manager Infomaniak, ouvrir **Outils avancés → Planificateur de tâches**, puis programmer l'URL de ce script avec le paramètre ?token= suivi du secret. Espacer les contrôles de 3 à 6 heures et activer les notifications d'échec et le journal d'exécution. Ne jamais partager cette URL complète.
4. Lancer manuellement une fois ; la sortie JSON doit indiquer checks=10. Un code HTTP 503 ou une liste alerts non vide signale une anomalie. Une erreur de téléchargement GitHub est également signalée.
5. Si le forfait prend en charge un lancement direct en PHP CLI, préférer cette option et lancer php /chemin/ondes_watchdog.php sans secret HTTP. Confirmer le mode de planification de l'hébergement avant déploiement.

Le fichier local de jeton est ignoré par Git. Garder les pages hors indexation et contrôler les permissions du fichier.

## Limites et coûts

La surveillance détecte les passages manqués, mais **ne relance pas les moteurs et ne publie rien**. Le rattrapage des recherches doit être audité dans chaque moteur ; aucun assouplissement des preuves n'est autorisé. Aucun runner privé GitHub ajouté, aucun nouveau forfait souscrit.
