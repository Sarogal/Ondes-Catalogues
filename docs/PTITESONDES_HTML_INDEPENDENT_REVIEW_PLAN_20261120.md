# P'tites Ondes — Planification nationale des preuves indépendantes
**20 novembre 2026 — PR empilée sur #493/#490/#486, en brouillon**

## But
Transformer la file HTML privée en liste de travaux indépendants, sans valider ni publier de fiche. Le planificateur est une étape préparatoire : les vérifications elles-mêmes et le publisher non musical restent à développer.

## Contrats
- Entrée : `html-review-candidates.json` validé et strictement privé dans `Sarogal/PtitesOndes` branche `automation/ptitesondes-intake`.
- Sortie facultative : `html-independent-worklist.json`, seulement dans le même dépôt privé, jamais dans un catalogue public.
- Modes `preview` (lecture seule) et `stage` (écriture atomique du fichier privé), sans commit ni push dans le script Python. Le pont GitHub existant reste **désactivé par défaut**, variable `PTITESONDES_HTML_QUEUE` non créée.
- Les résultats publics sont exclusivement des compteurs ; aucun titre, lien, ville, coordonnée, date/heure de séance ni identifiant individuel.
- Répartition entre villes par rotation équitable, sans liste géographique exhaustive et sans rejeter les lieux inconnus. Le suivi des droits institutionnels est effectué une fois par domaine, avec priorité aux interdictions explicites.

## Contrôles nécessaires avant une future publication
1. Nouvelle relecture de la séance officielle exacte (jour + heure).
2. Confirmation indépendante de l'organisateur, du public et des conditions d'accès ; tarif et âge inconnus ne sont pas inventés.
3. Recherche de l'adresse puis concordance géographique indépendante du lieu, même s'il n'était pas présent dans le registre.
4. Relecture du catalogue public servi par GitHub Pages et vérification des doublons par créneau horaire.
5. Vérification des droits de réutilisation au niveau de la source et de la fiche.
6. Validation du schéma append-only d'un futur publisher non musical.

## Garanties et limites
- Aucune action préparée ne signifie « preuve obtenue », « droit confirmé » ou « autorisation de publier ».
- Toutes les 14 catégories non musicales sont prises en charge ; les activités musicales conservent leur moteur existant.
- Les doublons déjà avérés et sources légalement restreintes restent bloqués. Des séances distinctes par horaire restent distinctes.
- Les adaptateurs HTML actuellement reconnus restent insuffisants pour une autonomie nationale ; un exécuteur de preuves indépendant et une découverte d'adaptateurs génériques doivent suivre.
- Aucune fusion, aucune modification de production, aucun déploiement et aucune intervention Infomaniak dans cette PR.

## CI
Tests hors réseau : multiséances, 14 catégories, équité villes et sources, ordre des restrictions, réessais, fichier privé atomique, rejeu sans fuite et refus d'approbations forgées.
