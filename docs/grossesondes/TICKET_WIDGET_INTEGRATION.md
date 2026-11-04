# Grosses Ondes — intégration du module d'affichage des billets

## Périmètre réel

- Le catalogue vérifié est publié sur `Ondes-Catalogues/docs/grossesondes/festivals.json`.
- Le **site en production** sur `https://grosses-ondes.fr/festivals/` est servi chez **Infomaniak**. Les fichiers `website/` du dépôt `Sarogal/GrossesOndes` sont une ancienne maquette **à ne pas redéployer**.
- Ce lot fournit deux ressources statiques autonomes, testées et publiables via GitHub Pages. Il **ne modifie pas le code Infomaniak** tant que sa version exacte n'est pas disponible. Le widget n'est donc pas encore visible sur le site en production.

## Ressources

- Script : `https://sarogal.github.io/Ondes-Catalogues/grossesondes/ticket-availability.js`
- CSS : `https://sarogal.github.io/Ondes-Catalogues/grossesondes/ticket-availability.css`
- Test : `node --test tests_js/test_grosses_ticket_widget.cjs`

Pour intégrer plus tard, **exclusivement dans la version actuellement déployée sur Infomaniak** :

```html
<link rel="stylesheet" href="https://sarogal.github.io/Ondes-Catalogues/grossesondes/ticket-availability.css">
<script defer src="https://sarogal.github.io/Ondes-Catalogues/grossesondes/ticket-availability.js"></script>
```

Après que le code existant a généré une fiche à partir de l'objet `festival` déjà chargé depuis le JSON public, ajouter **à la fin de son rendu** :

```js
// slot = conteneur dédié à cette seule fiche, sans contenu existant à écraser.
const slot = document.createElement("div");
card.appendChild(slot);
window.GrossesOndesTickets?.render(slot, festival);
```

Les identifiants `card` et `festival` sont **illustratifs** : ils doivent être adaptés aux fonctions et noms exacts de l'actuel `app.js` Infomaniak. Ne pas copier cette section à l'aveugle.

## Conditions strictes d'affichage

Le champ `ticketAvailability` doit présenter `scope: "per_category_only"`, `verifiedAt` au format YYYY-MM-DD, `source` **identique** au champ `officialSite` HTTPS du festival, et de 1 à 12 catégories `{name,status}` chacune avec une valeur parmi `sold_out`, `in_stock`, `limited_availability` ou `preorder`. Les catégories ont été vérifiées indépendamment côté synchroniseur public.

Le widget masque intégralement les informations de billets si la preuve a plus de **deux jours calendaires en Europe/Paris**, si elle porte une date future, si une donnée est incohérente, si l'édition est terminée ou si son statut évoque une annulation ou un report. Il n'affiche **jamais** « festival complet » et n'invente pas de prix.

Tous les titres et noms de billets sont ajoutés avec `textContent`, sans HTML dynamique. Le lien mène uniquement à l'URL officielle enregistrée et est ouvert en onglet séparé sans `opener`.

## Vérification de publication

1. Vérifier que le workflow `Grosses Ondes — affichage billetterie (tests isolés)` est vert.
2. La fusion d'une ressource lance le workflow `Grosses Ondes — publier les ressources de billetterie Pages`, qui verrouille les autres déploiements, contrôle l'intégrité du calendrier signé et copie `docs/` sans écrire de données. **La présence sur GitHub ne garantit pas la disponibilité Pages avant la fin de ce workflow.**
3. Vérifier que les deux fichiers statiques sont accessibles sur Pages ; ils ne seront pas injectés automatiquement dans Infomaniak.
4. Contrôler sur une fixture de festival qu'une catégorie « Épuisé » ne masque pas les autres catégories disponibles, et que la preuve disparaît le troisième jour.
5. Avant déploiement du raccordement dans le **vrai site**, obtenir les fichiers `app.js` et `festivals/index.html` depuis la production (pas la copie `website/`). Conserver une sauvegarde et tester la carte et la liste après intégration.

Ce module est une amélioration de présentation, **pas un système de vérification autonome** et pas une confirmation que les billets sont encore disponibles au moment de l'ouverture de la page.
