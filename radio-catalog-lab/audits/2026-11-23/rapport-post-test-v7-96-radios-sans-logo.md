# Grosses Ondes — Inventaire post-validation téléphone v7 (23 novembre 2026)

**Source :** branche de catalogue TEST v2 effectivement servie à l'APK, séquence 7, digest signé `f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa`.

**Validation réelle utilisateur :** affichage de **285 stations actives** et des nouveaux logos Exclusively sur Unihertz Tank 3 Pro, **sans recompilation**. Cela valide le téléchargement et l'affichage d'un nouveau catalogue et d'un lot de logos sur téléphone, **pas encore** les favoris, les flux de toutes les stations, Android Auto ni l'usage hors ligne.

## État signé

- 285 stations actives.
- 189 références de logos pour les stations actives ; 96 sans référence.
- 24 redirections d'anciennes fiches ; 320 identifiants GO historiques et 363 alias Radio Browser conservés dans le modèle.
- Les redirections sont structurellement contrôlées, mais **leur comportement sur des favoris préexistants doit encore être vérifié sur téléphone**.
- 96 stations restantes avec `logo: null` ; elles sont dans [l'inventaire CSV complet](./96-radios-actives-sans-logo-v7.csv).

## Regroupement pour retrouver les visuels

| Origine à investiguer | Nombre de radios sans logo |
|---|---:|
| Autres indépendantes | 89 |
| Radio Maximum | 3 |
| Radio Metal On | 3 |
| RauteMusik | 1 |
| **Total** | **96** |

## Plan de qualification des prochains logos

1. **Identité d'abord :** utiliser le `go_station_id`, l'URL du flux, le site de l'éditeur et les UUID Radio Browser pour éviter les faux rapprochements.
2. **Image véritable :** préférence pour la page de la radio et le CDN officiel ; autres annuaires uniquement comme piste, pas comme preuve d'identité.
3. **Vérifier les octets :** SHA-256, type MIME, dimensions, disponibilité et absence de redirection vers un visuel générique. Conserver les images en blobs immuables par SHA.
4. **Aucune suppression de logo valide :** les 189 fiches actives déjà couvertes conservent leurs logos, sauf correction explicitement vérifiée.
5. **Préparer v8 sur une branche dédiée** : schéma, contrôle de signature du prédécesseur v7, identités/favoris et validation hors production avant toute modification du pointeur actif.

### Garde-fous

Cette branche est **strictement documentaire**. Elle ne change ni le pointeur de la v7 TEST, ni les applications, ni `main`, ni la production ou le Play Store. Les groupes de provenance sont des priorités d'audit, pas une liste fermée empêchant la découverte autonome de nouvelles radios.
