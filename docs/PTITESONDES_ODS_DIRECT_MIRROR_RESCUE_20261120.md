# P'tites Ondes — Rattrapage privé OpenAgenda v2 lorsque le miroir ODS omet un UID
**20 novembre 2026 — PR brouillon. Aucune fusion ni mise en production.**

## Cause vérifiée
L'audit racine du 12 novembre a contrôlé 117 séances admissibles et trouvé 24 UIDs OpenAgenda non présents dans le miroir OpenDataSoft, 13 divergences d'URL canonique et 54 refus de destination familiale/musicale. Les 24 absences ont été confirmées par requêtes ODS terminées (non par simple timeout). Le tableau de bord privé du 20/11 montre un backlog de 441 dossiers, dont 141 en attente de preuve lieu/GPS. Ces familles de blocages ne doivent pas être confondues.

## Nouvel audit sans droits de publication
- `scripts/ptitesondes_ods_direct_mirror_absence_audit.py` : prend les leads privés OpenAgenda v2, les UIDs de calendriers configurés indépendamment dans `automation/sources.json` du dépôt privé et la clé publique OpenAgenda de lecture.
- Relit l'identité UID et slug des agendas depuis l'API v2, puis requête le miroir ODS par UID exact. **Seul le retour positif `uid_absent`** permet de poursuivre l'analyse directement dans OpenAgenda. Un timeout, une erreur HTTP 429, un JSON malformé, un UID non unique ou déjà présent interdisent le rattrapage.
- Vérifie ensuite la concordance du même UID, du statut public programmé, du mode physique, du titre, du lieu, de la commune et d'une séance annoncée à la date locale indiquée. Cela ne constitue qu'une déclaration de la source OpenAgenda.
- Les résultats détaillés, par UID et jour, restent dans la branche privée `automation/ptitesondes-intake`, fichier `automation-intake/ptitesondes/reports/ods-direct-mirror-audit.json`. Les logs publics ne contiennent que des compteurs anonymisés, aucune clé, titre, URL, UID, ville ou preuve.
- Le fichier est un diagnostic de rattrapage, pas un patch. Il ne renseigne jamais la valeur vrai pour `rights_reviewed`, `venue_geo_verified`, `organizer_independently_verified`, `family_audience_verified`, `approved` ou `publication_ready`.

## Workflow
- Réutilisation du pont `ptitesondes-private-intake-on-public-runners.yml` existant, sans nouvel horaire et sans dépenses de minutes privées additionnelles.
- Étape **inactive par défaut**, conditionnée par `PTITESONDES_ODS_DIRECT_AUDIT == enabled`. Cette variable n'est ni créée ni activée par la PR. `preview` ne modifie aucun fichier ; `stage` est exclusivement privé, si un jour autorisé.
- Le script refuse toute branche ou origine Git différente du dépôt privé autorisé. Il n'effectue aucun commit, push ou accès à la carte ; le pont privé protégé seul pourrait persister le diagnostic après activation.

## Pourquoi aucun nouveau résultat n'est publié par ce lot
Le miroir absent n'efface pas les autres obligations : original organisateur, âge/public réellement familial, adresse et GPS indépendants, droits de réutilisation, séances au bon horaire, doublons du catalogue live, modèle append-only. Le futur publisher devra exploiter les preuves directes v2 en complément de ces contrôles, sans convertir le simple diagnostic en passe-droit.

## Validation avant toute autorisation
- Tests adversariaux hors réseau : UID valide/absent/non unique, rate-limit, erreur réseau, source non enregistrée, changement de statut et lieu, fuseau ultramarin, conservation des jours distincts, interdiction des approbations forgées, accès privé Git, clé masquée, aucun push public.
- CI OpenAgenda v2, lint du pont partagé et synchroniseur général doivent réussir sur le dernier commit.
- L'absence actuelle du rapport d'audit privé `ods-direct-mirror-audit.json` est attendue : cette PR ne l'a ni créé en production, ni exécuté avec la clé privée.
