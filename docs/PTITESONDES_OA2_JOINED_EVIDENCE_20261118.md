# P'tites Ondes — Chaîne de diagnostics indépendants OA v2, GPS et séances

18 novembre 2026 — Branche isolée, **aucun déploiement**.

## But
Assembler sans exception par événement les modules de #379 (institution + JSON-LD Place + IGN/BAN exact + OA) et #384 (séances du site officiel en JSON-LD Event), sans lever les contrôles de publication.

Les fichiers d'origine des deux PR sont conservés ; `ptitesondes_openagenda_v2_joined_evidence.py` constitue un raccordement de **diagnostic pur, hors pipeline actif**, et non une autorisation de mise en ligne.

## Entrées et zones de confiance
- `lead` et `api_event` sont NON fiables pour homologuer une source.
- `reviewed_agenda` est issu d'un registre séparé.
- `reviewed_venue_source` et `reviewed_organizer` doivent provenir de registres validés indépendamment ; le code **ne les construit jamais à partir du lead**.
- `venue_page` et `organizer_page` doivent être récupérés par l'appelant à leur URL épinglée exacte, via transport HTTPS borné sans redirection ; `geojson` via IGN/BAN.
- L'appelant fournit les données à la fonction pure `diagnose_candidate(case, today)`. La fonction ne réalise aucun HTTP, ne modifie rien et ne consulte pas de secret.
- `diagnose_batch(cases, today)` accepte 1 à 60 cas et ne restitue que des compteurs de motifs fixés par le programme.

## Chaîne effectuée
1. Adresse et identifiant de lieu indépendants + géocodage au numéro + écart OA de 65 m maximum.
2. UID, agenda, pays, date, horaires, public, licence déclarative et structure OA v2.
3. Refus des séries UID multi-jours dans le chemin mono-jour, sans fiches artificielles.
4. Séances de l'organisateur confirmées **soit** dans une même unité de texte visible **soit** dans `schema.org/Event` JSON-LD, avec toutes les séances du jour, lieu, commune, date, fuseau et public familial visibles.
5. Compteur structurel anonymisé ; **aucun candidat approuvé ou publié**.

## Portes supplémentaires non franchies
- Propriété indépendante de l'organisateur et de l'agenda.
- Droits de réutilisation du contenu et des visuels.
- Âge exact, conditions d'accès et inscription.
- Déduplication avec l'historique et regroupement multi-jours.
- Classification éditoriale non musicale et autorisation de publication.
- Vérifications publisher, GitHub Pages puis affichage réel dans la carte.

Un résultat `structural_evidence_complete_other_gates_pending` ne doit **jamais** être assimilé à `safe_to_publish`.

## Suite avant toute intégration active
1. Récupérer des données réelles du backlog dans un environnement **privé** : interdiction de placer les candidats ou leurs URL dans des logs d'Actions publics.
2. Construire le sélecteur de sources officielles depuis un registre séparé, avec preuves de propriété et URL d'événements découvertes automatiquement.
3. Évaluer le funnel sur les 9 portes avec déduplication, accès, droit de publication, conditions familiales et catégorie.
4. Réconcilier les modifications des PR #379 et #384 sur une intégration propre, faire passer tous les tests et autoriser explicitement toute fusion / publication.

## Sécurité
La branche est isolée. Aucun workflow périodique, aucune clé, aucun cron, aucun catalogue public/privé ni publisher n'est modifié. Les tests sont hors réseau.
