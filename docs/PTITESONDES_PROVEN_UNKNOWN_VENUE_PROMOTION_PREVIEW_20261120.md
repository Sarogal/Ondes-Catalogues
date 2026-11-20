# P'tites Ondes — Prévalidation opt-in d'événements dans des lieux inconnus

**20 novembre 2026 — démonstration hors production**

## Problème réel

Dans `scripts/ptitesondes_candidate_promotion.py`, le préflight retenait les pistes à l'aide de `permitted()`, qui exigeait un lieu connu dans `VENUES` ou le catalogue des lieux déjà vérifiés. Même lorsque le dossier privé disposait d'une preuve GPS pour une nouvelle place ou un nouveau lieu, il n'existait aucune entrée dans le parcours de qualification des séances.

## Modification de la branche

Le préflight historique conserve **exactement** son comportement lorsqu'aucune preuve n'est fournie.

Une **option Python en mémoire seulement** accepte maintenant une table de preuves géographiques `venue_proofs`, indexées par la paire normalisée `(commune, lieu)`. Une preuve doit avoir été forgée par l'un des vérificateurs indépendants de lieu du même processus, via `VenueLocationProof`. Un booléen, un dict JSON provenant d'OpenAgenda, une paire de coordonnées déclarées ou une source auto-proclamée fiable ne suffisent pas.

Pour chaque candidat :

1. L'identité UID + date + URL de la piste doit toujours être cohérente.
2. Le lieu est recherché d'abord dans les registres déjà vérifiés ; pour un lieu nouveau, la preuve authentique de la paire commune/lieu est utilisée, en mémoire.
3. Les coordonnées du document ODS/événement doivent concorder à 65 m avec la preuve indépendante.
4. Le titre, le statut programmé, les horaires exacts, la catégorie musicale, la commune, le département et la région restent examinés par `make_event()`.
5. La déduplication des événements et des dates déjà publiées, la validation du schéma et le vérificateur officiel de l'organisateur et des représentations restent tous appelés.
6. Une représentation refusée par le vérificateur officiel reste refusée ; un événement hors périmètre éditorial, comme un simple goûter, reste refusé.
7. Le patch demeure **`safe_to_publish: false`** et la PR ne modifie aucun catalogue public.

Ce parcours ne transmet pas un dossier de preuve via des fichiers persistés : les preuves actuellement conçues sont **éphémères**, scellées en mémoire, et ne peuvent être simplement reconstruites à partir du seul rapport du préflight géographique. Le futur orchestrateur devra rejouer les vérifications pertinentes au moment de l'admission, ou définir un format de preuve authentifié et réévalué avec les mêmes garanties.

## Portée éditoriale

Le chemin `category_for()` n'admet historiquement que les sorties musicales explicites pour les enfants. Les contes non musicaux, lectures d'histoires et spectacles jeunesse sont travaillés séparément dans la PR #537 et ne doivent être raccordés qu'après tests propres à leur catégorie et adaptation du schéma de publication.

Les lieux inconnus ne sont **pas** un motif de rejet éditorial. Les événements non conformes, sans horaires, réservés aux scolaires ou sans source crédible le restent.

## Tests

`tests/test_ptitesondes_proven_unknown_venue_promotion.py` vérifie :

- Lieu inconnu jamais admis à défaut de preuve.
- Place sans numéro admise au **seul premier filtre géographique** via un témoin officiel + OSM, et progression en prévisualisation seulement si tous les autres tests passent.
- Fausse preuve JSON, mauvaise paire commune/lieu, preuve périmée et coordonnées de source divergentes bloquées.
- L'organisateur non vérifié bloque même une place correctement géolocalisée.
- Un goûter ordinaire au parc ne peut pas franchir la vérification de catégorie.
- Les rapports publics restent des compteurs sans données de lieu ou d'événement.

## Limite d'autonomie

Ce nouveau paramètre est opt-in uniquement depuis le code Python, **non accessible depuis les workflows ou CLI de production**. Aucune activation de la chaîne publication n'a été effectuée. Les 79 lieux privés ne sont toujours pas automatiquement homologués. Les campagnes par lots et la certification des séances doivent être liées de manière sûre avant toute activation.

**Aucune fusion, aucune modification de la production, aucun nouveau cron, aucune modification des garanties de publication.**
