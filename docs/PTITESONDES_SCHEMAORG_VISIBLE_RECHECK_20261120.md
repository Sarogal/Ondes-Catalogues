# P'tites Ondes — Relecture visible indépendante des pistes Schema.org
**20 novembre 2026 — lot préparatoire en brouillon, dépendant de #498.**

## Problème
Une fiche JSON-LD Schema.org Event peut annoncer le lieu, le jour et l'heure sans que le contenu visible de la page confirme cette séance. Elle peut aussi être dépassée ou différer de la programmation réelle. Les pistes privées ne doivent jamais être admises seulement sur leur représentation structurée.

## Nouvelle procédure
1. Lire `html-schemaorg-hints.json` exclusivement dans le dépôt privé authentifié, en validant chaque dossier et en rejetant tout drapeau `approved`, `published`, `rights_reviewed` ou faux justificatif.
2. Récupérer la liste des sources institutionnelles et leurs fuseaux depuis les **registres commis indépendamment**. Une piste dont l'hôte ou le chemin n'est plus autorisé reste en attente. Une source explicitement restreinte reste bloquée.
3. **Relire l'index actuel** de chaque source retenue, et exiger que l'URL précise de la fiche y soit encore visible. Une URL connue seulement par la piste ne suffit pas.
4. Relire par HTTPS exact et sans redirection la page fille encore référencée. Mutualiser le téléchargement pour plusieurs créneaux de la même page.
5. Faire vérifier par le contrôle existant la présence visible du titre, du lieu, du jour et de l'heure exacte dans le même bloc, l'absence de contradiction et le public familial. Une métadonnée cachée ne vaut jamais preuve visible.
6. Réinjecter les seuls dossiers ayant réussi cette première corroboration dans le routeur HTML générique existant, qui recontrôle les faits et les ajoute éventuellement à la file `html-review-candidates.json`. Ils restent **en attente de revue indépendante**, pas en publication.
7. Avant le lot, relire le catalogue public servi par GitHub Pages et confirmer l'égalité avec le catalogue versionné. Une ancienne date de modification des données n'est pas bloquante en elle-même.

## Fonctionnement et sécurité
- Mode `preview` entièrement sans écriture, mode `stage` uniquement dans `Sarogal/PtitesOndes`, branche `automation/ptitesondes-intake`.
- L'étape du workflow partagé exige **deux opt-ins distincts**, `PTITESONDES_SCHEMAORG_HINTS=enabled` et `PTITESONDES_SCHEMAORG_RECHECK=enabled`. La PR ne crée ni n'active ces variables.
- Aucun nouveau cron, aucun nouveau runner privé, aucune utilisation des données de la piste comme preuve d'organisateur, de GPS, de droits ou de disponibilité.
- Rotation équitable entre communes ; les séances multiples gardent leur heure propre. Les catégories encore inconnues ne sont pas réétiquetées automatiquement.
- Un index indisponible ou une heure non visible maintient les dossiers dans la file d'indices. Aucun événement ne disparaît du catalogue existant, et aucun élément n'est approuvé ni publié.

## État de l'autonomie
Cette transition **piste → séance visible → dossier privé** est préparée. Les contrôles indépendants de l'organisateur, de l'adresse/GPS, des droits et des doublons live à l'instant de publication, puis le publisher append-only non musical, manquent encore.
De plus, le registre de sources structurées ne contient qu'un pilote institutionnel : la découverte automatique et fiable des agendas nationaux doit être un chantier séparé. La couverture nationale complète n'est donc pas acquise.

## CI
Tests synthétiques des deux horaires sur une page, conservation des sources indisponibles, prévention des pages retirées de l'index, JSON-LD non visible, rejet des sources interdites et des champs falsifiés, contrôle live, confidentialité du runner et verrouillage des variables.
