# Grosses Ondes — inventaire générique des fournisseurs de logos indisponibles

**21 novembre 2026 — audit GitHub Actions non publiant, génération radio TEST 4.**

[Exécution réussie #44930305125](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44930305125), archive `go-v5-all-failed-provider-groups-review-only`.

## Résultats

Sur les **310 radios historiques**, 257 possèdent une association au manifeste public v5, dont 170 des octets validés, et **87 associations à des fichiers non validés**. Ces 87 associations concernent **78 URL distinctes et 16 hôtes**.

Le rapport d'audit de tous les UUID (historiques + huit hors inventaire) comptait 79 URL non validées. L'écart d'une URL correspond au périmètre des huit identifiants absents du lot historique — et ne doit pas être traité comme une station à supprimer.

| Hôte de l'image en échec | Radios historiques | URL distinctes | Sans URL dans le bootstrap | Problème |
|---|---:|---:|---:|---|
| `radcap.ru` | **67** | **61** | **41** | URLError |
| `www.maximum.ru` | 3 | 3 | 3 | InventoryError |
| `storage.googleapis.com` | 3 | 1 | 1 | InventoryError |
| `www.hardradio.com` | 2 | 1 | 2 | InventoryError |
| Autres fournisseurs | 12 | 12 | 5 | Format, MIME, réseau ou HTTP |

Les autres hôtes sont ARFM, FemMetal, Maximum, Metalradio.at, MyRadio24, Radio Diabolus, Radio Gora, Radio Tangra, Rock FM Nicaragua, Wix Static, Christian Hardrock et Radio Metal. Les 87 associations en échec concernent aussi des fournisseurs hors RADCAP : il ne faut pas créer une correction spéciale bloquant ceux-ci.

**53 radios historiques** sont totalement absentes des associations publiques v5. Elles sont ventilées dans le rapport par **hôte de la page historique** pour orienter une nouvelle découverte non limitée à une liste connue. Deux d'entre elles ont leur page historique sous `www.radcap.ru` et sont distinctes des 67 entrées avec image RADCAP v5 en échec.

## Garanties

- `radio-catalog-lab/tools/group_unverified_v5_artwork_sources.py` regroupe **dynamiquement** les URLs par hôte, sans liste fermée de fournisseur, radio, nom ou genre.
- Le contrôle s'appuie uniquement sur l'archive SHA préexistante et les 310 UUID du bootstrap. Il n'effectue **aucun réseau** vers les fournisseurs indisponibles.
- Il conserve la présence ou l'absence d'une ancienne URL V64, ainsi que l'URL d'origine. Les flux, identifiants et favoris ne sont jamais changés.
- Les erreurs réseau ne sont jamais des preuves de logo incorrect ou de radio hors service.
- Les rapports contiennent `remove_any_radio=false`, `publication_allowed=false`, `signed_catalog_created=false` ; pas de manifeste TEST actif ni changement Play Store.

## Suite

1. Diagnostiquer séparément les hôtes en échec et leurs codes d'erreur (notamment TLS pour RADCAP), avec backoff persistant par fournisseur et sans impact sur les autres.
2. Essayer les pages officielles HTTPS ou sources alternatives vérifiables, avec identité de canal indépendante, SHA des octets et décodage réel.
3. Rechercher de meilleurs logos quand l'image actuelle est de petite dimension, sans agrandir artificiellement une image basse définition.
4. Ne réintégrer les logos qu'après preuve de provenance officielle et revue visuelle ; ne jamais fusionner des stations partageant un logo.
5. Conserver en priorité les fichiers et références V64 existants sur téléphone jusqu'à une vraie migration du cache SHA.

Suivi : [issue #685](https://github.com/Sarogal/Ondes-Catalogues/issues/685). L'outillage n'active aucune image, ne déclenche aucun cache client et ne signe aucun sidecar.
