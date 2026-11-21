# Grosses Ondes — 53 radios historiques sans association artwork v5

**21 novembre 2026 — TEST uniquement, découverte ouverte et non publiable.**

## Recensement

Le rapport de défaillances de la [PR #687](https://github.com/Sarogal/Ondes-Catalogues/pull/687) a identifié **53 UUID historiques** non représentés dans les associations du manifeste public v5. Ces radios demeurent conservées et écoutables indépendamment des logos.

[Workflow en huit lots #44931329398](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44931329398) — **SUCCESS** :

- **53** radios uniques explorées ;
- **23** pages historiques ont produit des métadonnées d'images candidates ;
- **27** pages sans image reconnue (ou momentanément indisponibles) ;
- **3** pages sans adresse HTTPS sûre à consulter ;
- **58** références d'images proposées par des pages, principalement `og:image` ou favicons ;
- **0** image téléchargée dans ce premier audit ; **0** association approuvée.

Ce résultat concerne uniquement les radios historiques absentes du manifeste v5, pas les 87 associations v5 en erreur réseau étudiées séparément.

## Nouvelles pistes

Des références possibles ont été remontées pour Heavy Metal History Radio, Código Metal Radio, Nuclear Fallout Radio, Megarock Radio, Pure Rock KNAC, 181.FM HairBand, BOLLOCKS, RSTLSS, Metal Heads, Radio Narcan et d'autres. Il faut distinguer un vrai logo de la radio d'un favicon commun, d'une jaquette d'article, d'une photo d'artiste ou d'une simple image de partage.

Les réseaux `Exclusively` / `you.radio`, `Virgin Radio`, `RauteMusik` et autres ont souvent des favicons génériques qui **ne prouvent pas** l'identité graphique du sous-canal. Ne jamais fusionner deux stations parce qu'elles partagent le même logo de réseau.

Le workflow [preuve SHA des images OG](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44931636306) sélectionne au plus **deux `og:image` / `twitter:image` par UUID** et ignore les favicons. Il recalcule le SHA-256, décode les vrais octets, relève la résolution et le MIME, puis conserve le résultat **pour revue uniquement**, même si le fichier est techniquement valide.

## Garde-fous

- Aucun fournisseur, UUID ou genre en whitelist ; les pages proviennent de l'inventaire historique et le regroupement demeure dynamique.
- Les pages HTTP historiques ne sont **pas** interrogées en clair ; seules leurs équivalentes HTTPS peuvent être testées.
- DNS, URL, redirections, temps d'attente et limites de taille sont protégés par l'outillage existant.
- Tous les candidats restent `verified_image_bytes=false` dans le premier inventaire ; les probes ultérieures ne décident jamais d'une identité visuelle.
- Les flux, favoris, UUID et URL de logos V64 restent inchangés.
- Les rapports restent `identity_visual_approved=false`, `publication_allowed=false`, `signed_catalog_created=false`. Le catalogue radio TEST reste sur la séquence 4, l'artwork actif est absent.
- Aucun changement Play Store ni fusion en production.

**Suite :** examiner les images OG qui passent le SHA et mesurent au moins 192 px, confirmer l'identité du canal à partir d'une source officielle, puis choisir explicitement les premières associations à ajouter dans une nouvelle génération artwork TEST. 
