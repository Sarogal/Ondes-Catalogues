# Grosses Ondes — Contrôle réseau réel : laboratoire public, sans catalogue privé

**20 novembre 2026 — exécution bornée, non publiante.**

La première campagne privée de cinq flux historiques avait été préparée
sur la branche isolée `GrossesOndes/feature/radio-release1-live-canary-20261120`.
Son Action [#44808081117](https://github.com/Sarogal/GrossesOndes/actions/runs/44808081117)
a échoué **avant toute étape exécutée** : aucun journal et aucune
preuve de vérification audio. La cause exacte (éligibilité du runner,
facturation, restrictions de dépôt, etc.) n'a pas pu être vérifiée.
Ne pas considérer les stations historiques comme sondées.

Le présent laboratoire teste uniquement le **transport réseau**, en
utilisant une page publique courante de l'API Radio Browser sur le
terme `metal`, sans extraire le fichier privé des 310 stations.

Chaîne :
1. Une seule requête GET de découverte à un miroir Radio Browser officiel ;
   au maximum 100 entrées lues.
2. Sélection d'au maximum **cinq candidats** ayant un UUID distinct, une
   URL publique sans identifiants, un codec *annoncé* MP3/AAC (ou suffixe
   de fichier associé) et aucune extension .m3u8. Aucun UUID de station
   fixé à l'avance, aucune liste exhaustive.
3. Planification via `radio_catalog_probe_batch_plan.py`, génération
   d'entrées avec URL **uniquement** dans un dossier éphémère du runner.
4. Sondage des flux via `PinnedHttpTransport` et `probe_candidates`
   existants, avec limites de requête, DNS public, protection contre les
   redirections dangereuses, vérification TLS et échantillon de 512 octets.
5. Réconciliation exacte UUID+SHA avec
   `radio_catalog_batch_evidence_bridge.py` et registre par variante.
6. Nettoyage automatique des fichiers à URL brute ; archivage de
   **seuls** les résumés techniques et observations sans URL ni audio,
   pendant sept jours.

Cette CI n'examine pas le catalogue privé. Le champ de bilan
`historicalPrivateStationsChecked` vaut donc **0**, même si une radio
publique découverte s'avérait par hasard également présente dans
Grosses Ondes. Pour reconnaître un chevauchement éventuel, la
comparaison devra se faire ultérieurement **dans un environnement
privé**, par UUID et non en publiant la liste historique.

**Non acquis :** pas de second jour de preuve, pas de confirmation
de décodage continu, pas de contrôle HLS, pas d'admission éditoriale,
pas de signature de release, pas de changement de cache des logos ou
Android Auto, pas de mise à jour Play Store.

Le workflow est limité à sa branche, sans `schedule`,
avec tests hors réseau obligatoires et aucune fusion de production.

## Première exécution réelle : 20 novembre 2026

La [CI publique #44808485360](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44808485360)
est **SUCCESS** :
- **21 tests hors réseau réussis** (6 nouveaux tests de contrôle direct
  et 15 tests du pont Release 1).
- **1 page Radio Browser de 100 entrées**, dont **90** candidates
  directes d'après leur codec déclaré ou leur URL.
- **5 flux réellement interrogés** par le transport DNS/TLS/SSRF contrôlé.
  **4** ont produit une signature audio reconnaissable
  (`audio_sample_ok`), **1** une indication MIME uniquement
  (`audio_mime_only`).
- **0 validation technique**, **0 approbation éditoriale**,
  **0 suppression historique**, **0 publication**.
- Artefact conservé 7 jours :
  `go-radio-public-transport-canary-evidence` (rapports **sans URL**).

**Distinction importante :** l'attribution éventuelle de ces cinq UUID
à des stations du catalogue privé n'a pas été vérifiée dans ce workflow
public et ne doit pas être inférée de ce rapport. Un seul résultat réseau
positif ne confirme pas la stabilité audio dans le temps.
