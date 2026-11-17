# P'tites Ondes — Prévalidateur familial national indépendant

**17 novembre 2026 — DRAFT, lecture seule, aucune admission ni publication.**

## Objectif et dépendances

Ce chantier est empilé sur la **PR #342 (classification nationale)**, sans
modifier les quatre catégories municipales spécifiques de la chaîne
**#323 → #341**, ni la prévisualisation cartographique **#327**.
Il vise les activités datées non musicales adaptées aux enfants, en
**métropole, Corse, Guadeloupe, Martinique, Guyane, La Réunion et Mayotte**.
Les 7 catégories musicales historiques et le circuit OpenAgenda conservent
leur comportement existant.

## Ce qui est réellement vérifié

Le module `scripts/ptitesondes_family_national_source_preflight.py` propose
`inspect_family_national_preflight(catalogue, bundles, today, *,
catalogue_sha256, trusted_official_hosts, venue_registry, source_get)`.

Chaque paquet comprend **une proposition de catégorie** conforme au contrat
#342 (`scope`) et **un dossier de vérification ponctuelle** (`source`)
avec URL organisateur, heure locale, point GPS, identité du lieu et région.
Les tests ne fournissent que des scénarios fictifs.

1. **Catalogue :** empreinte SHA exacte et unicité des identifiants ; toutes
   les 548 fiches de référence du 16/11 sont préservées sans mutation.
   Une publication ultérieure changeant l'empreinte invalide ce contrôle.
2. **Confiance de l'origine :** le domaine HTTPS de l'URL doit appartenir
   exactement à une liste de domaines d'organisateurs **homologués hors
   des propositions des collecteurs** ; un agrégateur ou sous-domaine non
   autorisé ne peut entrer par ressemblance.
3. **Source effectivement relue :** page HTML de la séance, identité
   exacte du titre, du lieu et de la ville, date de séance explicite,
   heure locale, mention du public enfant/famille ; les bornes d'âge
   chiffrées sont recontrôlées, non déduites de l'étiquette « famille ».
4. **Accès :** une affirmation explicite « gratuit », « tarif en euros »
   ou « sans inscription » doit se retrouver sur la page organisatrice.
   Le silence garde le prix et l'inscription **non précisés** ;
   une contradiction reste bloquée.
5. **Sécurité :** annulation, report et complet refusés ; contrôle de
   doublon titre/ville/lieu/date dans le lot et contre le catalogue,
   y compris les fiches d'une source musicale ou OpenAgenda.
6. **Géographie :** un lieu et ses coordonnées doivent correspondre à
   une entrée d'un registre distinct, avec sources institutionnelle et
   cartographique HTTPS de domaines différents ; seuil maximal **65 m**.

### Limites qui restent bloquantes

Ce module **ne peut pas prouver** qu'un domaine ajouté à la liste
a réellement été homologué par une personne, ni que la page est signée
par l'organisateur. Il ne refait pas la vérification indépendante auprès
du fournisseur GPS externe et n'interroge **pas** GitHub privé pour des
attestations humaines. La vérification HTML générique se limite à un
contrat volontairement strict : certaines pages officielles nécessiteront
un adaptateur spécifique, lequel devra être testé et audité avant usage.

Un résultat `source_preflight_batch_passed=true` signifie seulement que
les indices de la page et du lieu sont **cohérents avec les données de
test ou la liste de confiance fournie**. Ce n'est ni une admission, ni une
preuve cryptographique, ni une autorisation du publieur.

Les **lieux permanents** ne passent pas dans ce prévalidateur
d'événements : ils suivent leur propre parcours de validation.
Une animation datée organisée dans un lieu permanent reste contrôlable
comme sortie distincte.

## Contrat de non-publication

La sortie contient des compteurs et motifs de blocage **agrégés**,
sans événements, propositions individuelles, `patch.v1`, `additions`,
jeton, ou catalogue modifié. Champs toujours imposés :

- `publication_ready=false`
- `approval_granted_to_publisher=false`
- `public_writes=0`
- `historical_records_modified=0`
- `historical_records_deleted=0`

Les scripts `merge_policy.py`, `proof_text.py`, prévalidateurs
OpenAgenda, catalogue JSON, carte, site Infomaniak, crons et
workflows privés ne sont pas modifiés.

## Tests et développement suivant

Le workflow public sans secret `ptitesondes-family-national-source-preflight-tests.yml`
exécute des tests adversariaux **hors réseau** ; ses seules autorisations
sont `contents: read` et il n'a aucun `schedule`.
La suite complète existante du synchroniseur doit rester verte.

La phase suivante devra ajouter **des adaptateurs officiels par source**
et une vérification géographique externe actualisée, le registre de
confiance homologué en GitHub, la revue privée authentifiée,
les preuves réelles et l'autorisation éditoriale, puis un contrôle
terminal d'admission distinct (comme les exigences de la chaîne #341).
Le prochain prototype cartographique sera empilé sur la **PR #327**
sans publication, et conservera les six zones et les filtres d'âge.

Aucune fusion, activation ou publication n'est autorisée par cette PR.
