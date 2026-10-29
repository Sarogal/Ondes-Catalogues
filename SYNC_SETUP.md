# Mise en service — synchronisation cloud P'tites Ondes

Le code est installé. La publication reste **désactivée par défaut** : la variable GitHub Actions `PTITESONDES_CLOUD_SYNC` n'existe pas encore (ou n'est pas égale à `enabled`).

## Principes de sécurité
- Seul `Sarogal/PtitesOndes`, branche `automation/ptitesondes-intake`, fournit les patches privés.
- Le compte public `Sarogal/Ondes-Catalogues` stocke uniquement les événements acceptés.
- La production historique `https://ptitesondes.fr/config/sorties.json` est l'ancre de validation. Aucune fiche historique ne peut être supprimée ou modifiée.
- Tout événement doit avoir une preuve officielle **indépendante et structurée** (JSON-LD : titre, date et lieu), plus une géolocalisation vérifiable (source officielle ou lieu équivalent déjà public). Les autres restent en attente.
- Les mises à jour d'événements existants sont bloquées tant que leur audit séparé n'est pas implémenté.
- Le script ne fait **jamais** de publication : seule la tâche GitHub Actions peut commiter puis déployer, après les tests.
- Si aucune nouvelle fiche ne passe les contrôles, aucune écriture ne se produit. Le flux quotidien peut donc produire **zéro ajout**, même si la veille propose de nouveaux candidats.

## Configuration unique du secret de lecture seule
1. Ouvrir GitHub > Settings (du compte) > Developer settings > Personal access tokens > Fine-grained tokens > Generate new token.
2. Resource owner : **Sarogal**. Repository access : **Only select repositories**, sélectionner uniquement **PtitesOndes**.
3. Repository permissions : **Contents: Read-only**. Aucun accès en écriture, aucune permission Actions ou Administration. Choisir une date d'expiration adaptée et renouveler avant expiration.
4. Copier le token **directement** dans GitHub, et jamais dans une conversation ni un fichier de dépôt :
   `https://github.com/Sarogal/Ondes-Catalogues/settings/secrets/actions` > New repository secret.
   Nom **PRIVATE_INTAKE_READ_TOKEN**, valeur : token généré.

## Tests avant activation
1. Ouvrir `https://github.com/Sarogal/Ondes-Catalogues/actions/workflows/sync-tests.yml`, lancer **Run workflow**. Vérifier les tests.
2. Ouvrir `https://github.com/Sarogal/Ondes-Catalogues/actions/workflows/ptitesondes-cloud-sync.yml`, choisir **Run workflow > preview** : compare les catalogues, vérifie indépendamment les nouveautés, mais **ne commite et ne déploie rien**.
3. Lire dans le résumé de la tâche combien de fiches sont **acceptées** et combien restent **en attente**. Tout problème doit être corrigé avant activation.

## Activation des publications
Une fois les contrôles satisfaisants, ouvrir :
`https://github.com/Sarogal/Ondes-Catalogues/settings/variables/actions`
et créer la variable de dépôt `PTITESONDES_CLOUD_SYNC` avec la valeur exacte **enabled**.

À partir de là, la tâche `P'tites Ondes — synchronisation cloud securisee` est planifiée vers **10 h 20 UTC** chaque jour (soit 11 h 20 l'hiver et 12 h 20 l'été en France), après la veille ChatGPT du matin. L'horaire exact des tâches GitHub Actions n'est pas garanti.

Le déploiement est également possible manuellement avec **Run workflow > publish**, après activation de la variable.

## Arrêt immédiat, retour arrière
- Pour suspendre tout nouveau déploiement, effacer la variable `PTITESONDES_CLOUD_SYNC` (ou lui donner une autre valeur).
- Pour revenir à une ancienne version du catalogue, restaurer le commit précédent de `docs/ptitesondes/sorties.json` puis lancer le workflow manuel de référence.
- L'adresse `https://ptitesondes.fr/config/sorties.json` demeure en secours pour le site. Les scripts du site ne sont pas modifiés par la tâche cloud.

## Limites
La vérification automatique est volontairement exigeante. Une source officielle qui ne fournit pas de JSON-LD exploitable ne permet **pas** une publication automatique, même si l'événement est réel. Les fiches nouvelles de lieux non connus risquent de rester en attente. Les contrôles actuels ne garantissent pas, à eux seuls, tous les tarifs, âges et horaires annoncés : maintenir les sources de veille exigeantes et auditer les cas douteux avant d'assouplir la politique.
