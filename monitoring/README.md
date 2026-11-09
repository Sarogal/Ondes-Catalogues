# Ondes — surveillance indépendante des passages programmés

Le script monitoring/ondes_watchdog.php est un contrôleur **en lecture seule** du dépôt public Sarogal/Ondes-Catalogues. Il n'utilise aucun token privé et ne modifie ni intake, ni fiches, ni catalogues. Il vérifie via l'API GitHub les créneaux des collectes, prévalidations et synchronisations réellement exécutés avec succès, puis le schéma et les volumes minimum des quatre JSON servis par GitHub Pages.

Le contrôle examine les créneaux prévus sur les dernières 27 heures, en laissant **9 heures** de marge pour les retards potentiellement très importants. Une exécution manuelle ne remplace pas un déclenchement programmé. **Attention :** GitHub n'expose pas l'horaire cron exact dans la liste des runs ; l'association entre un passage prévu et une exécution très retardée est indicative. Les alertes de créneau doivent donc être vérifiées avec l'historique des runs et le résultat des jobs, et non interprétées comme une preuve absolue d'absence. Ce contrôle ne garantit pas la découverte de toutes les dates et ne compare pas le JSON public au dépôt main : cela appartient à la PR de réconciliation Pages #135.

## Contrôles locaux et GitHub

Tests : php -l monitoring/ondes_watchdog.php ; php monitoring/ondes_watchdog.php --self-test.

Le workflow en lecture seule ondes-public-watchdog.yml se lance deux fois par jour et peut être lancé manuellement. Il peut lui-même manquer lors d'une panne GitHub : il ne remplace pas la surveillance indépendante.

## Surveillance indépendante sans hébergement PHP : Healthchecks.io

**Important : l’hébergement Infomaniak Starter est statique (pas de PHP ni planificateur de tâches). Ne jamais y déposer un script PHP, un jeton local, un ZIP avec des secrets, ou une URL privée.** Un serveur statique peut afficher directement le code source PHP, ce qui expose les secrets placés dans le répertoire public.

La solution retenue pour Starter est un **témoin externe** : quand le workflow GitHub `ondes-public-watchdog.yml` termine **toutes** ses vérifications avec succès, il envoie un ping à Healthchecks.io depuis le runner public déjà utilisé. Si GitHub ne démarre pas le workflow, si la vérification échoue ou si un ping ne parvient pas au témoin externe, Healthchecks peut prévenir par e-mail sans dépendre de GitHub pour l’alerte.

### Activation manuelle (sans carte bancaire ni nouveau runner)

1. Créer un compte **Hobbyist gratuit** sur https://healthchecks.io et un seul contrôle nommé « Ondes — watchdog public ». Ne pas souscrire de forfait supérieur.
2. Configurer ce contrôle en mode **Cron**, expression `29 4,16 * * *`, fuseau `UTC`, délai de grâce initial `9 heures`. Les horaires correspondent aux crons du workflow existant.
3. Configurer la notification **e-mail** dans Healthchecks et vérifier que l’intégration est active.
4. Copier l’URL de ping générée par Healthchecks (`https://hc-ping.com/…`) **uniquement** dans le secret Actions du dépôt public GitHub `Sarogal/Ondes-Catalogues`, nommé `HEALTHCHECKS_ONDES_PING_URL`. Ne pas publier la valeur dans une PR, un fichier versionné, un ticket ou un message.
5. À partir du prochain **déclenchement programmé réussi** de `Ondes — surveillance publique en lecture seule`, un ping doit apparaître dans Healthchecks. Les exécutions manuelles et les PR **ne déclenchent pas le ping**, pour ne pas masquer un cron manquant.
6. Inspecter la prochaine exécution réelle et tester l’envoi d’e-mail via l’interface du service. Tant que le secret est absent, le workflow reste actif mais n’émet aucun ping.

Le ping est exécuté comme **étape du job existant** après la vérification, sans workflow ni runner additionnel. Un échec du service de ping est journalisé comme avertissement et ne transforme pas une collecte en panne ; l’absence de ping est détectée par le témoin externe.

Ce témoin observe que le **contrôle GitHub s’est terminé sans alerte**, pas que chaque nouvelle date a été publiée. Une exécution verte ne certifie pas non plus une mise à jour de carte ; la réconciliation de GitHub Pages doit rester un contrôle séparé (PR #135).

## Option réservée à un hébergement PHP existant (non applicable à Starter)

Le script `ondes_watchdog.php` reste disponible pour une exécution PHP **en ligne de commande** sur un hébergement disposant de PHP et d’un cron. Préférer un dossier hors répertoire public, sans accès HTTP et sans aucun jeton dans le document root. Ne jamais acheter un hébergement supplémentaire uniquement pour ce watchdog.

## Limites et coûts

Le témoin externe **détecte et alerte**, mais ne relance pas les moteurs et ne publie rien. Les règles de vérification des sources restent inchangées. À la date de vérification, Healthchecks.io permet 20 contrôles dans son offre Hobbyist gratuite ; cette installation n’en utilise qu’un. Le service pourra modifier ses conditions à l’avenir. Aucun runner GitHub privé ajouté.
