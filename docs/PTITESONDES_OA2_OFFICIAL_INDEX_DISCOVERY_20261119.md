# P’tites Ondes — découverte générique des racines OpenAgenda depuis les index institutionnels

**19 novembre 2026 — diagnostic isolé, sans approbation, publication ou modification du registre.**

## Ce qui manquait

La PR #399 savait confirmer une association entre **une page institutionnelle
déjà épinglée** et **un agenda OpenAgenda déjà connu**. La PR #413 reliait
cette référence à la lecture réelle d'une fiche OA v2, mais l'ajout de nouveaux
agendas nécessitait toujours de nommer leur `agenda_slug` avant même
d'inspecter la page officielle.

`scripts/ptitesondes_oa2_official_index_discovery.py` ajoute la découverte
de **plusieurs racines d'agenda depuis une même page institutionnelle** déjà
reconnue, sans adaptation à chaque sortie et sans supposer qu'un lien constitue
une approbation.

## Contrat de découverte

- La sélection de la page officielle vient exclusivement d'une épingle
  indépendante `approved_host` + `exact_index_url`, jamais du candidat
  OpenAgenda, de son URL, d'ODS ou d'un extrait de recherche.
- `discover_from_live_official_index` peut récupérer cette page en HTTPS
  avec le lecteur existant `fetch_official_page` : GET exact, redirections
  refusées, type HTML contrôlé, réponse bornée.
- Les ancres visibles d'agenda / événements / programmation / calendrier
  sont analysées, avec validation stricte du domaine
  `openagenda.com` et de l'URL racine exacte.
- Les slugs d'agenda observés sont dédoublonnés. Les correspondances à la
  liste fournie de métadonnées UID + slug sont uniquement des **indices**.
- Les agendas absents de cette liste sont conservés comme **candidats à
  résolution d'UID**, plutôt que rejetés silencieusement.
- Plusieurs métadonnées pour un même slug restent en attente :
  **aucune première correspondance n'est choisie arbitrairement**.

## Modèle de sortie

`private_review_queue` contient des **propositions provisoires** et
explicitement non approuvées (`approved=False`, `review_required=True`,
`timezone=None`). Les champs ne sont volontairement **pas** compatibles
avec la structure des cinq champs attendus par le registre approuvé de #399.

`redacted_discovery_counts` est la seule vue acceptable pour un rapport
public : compteurs fixes de racines visibles, correspondances suggérées,
agendas sans UID résolu et cas ambigus. Aucun titre, ville, host, URL,
slug ou UID ne peut sortir dans ce rapport.

## Limitations assumées

Cette PR n'apporte **aucune institution réellement vérifiée** à la liste
nationale. Même un lien visible sur un site municipal ne prouve pas le
propriétaire juridique de l'agenda ni la véracité d'une séance spécifique.
Les métadonnées API peuvent être autodéclarées ; aucune approbation ne peut
être induite d'un `official=1` ou d'un lien présent dans OpenAgenda.

Prochain travail en environnement privé de confiance :
1. Constituer et revoir un registre d'index officiels municipaux,
   départementaux, bibliothèques, musées et autres organisateurs, sur
   toutes les régions et les territoires ultramarins.
2. Exécuter le lecteur indépendant sur ces pages et enregistrer les
   propositions dans un espace de revue **privé**.
3. Résoudre les UID par de véritables lectures OpenAgenda v2 ; faire valider
   l'identité administrative et le fuseau horaire par institution.
4. Seulement ensuite, ajouter les entrées explicitement confirmées au
   registre approuvé (pas automatiquement via ce module) et utiliser les
   validations par séance, lieu, public, droits, déduplication et publisher.

CI : tests adversariaux sans réseau, sans secret, sans cron, lecture seule.
Aucun changement d'Actions de collecte, de catalogue GitHub Pages ou
d'Infomaniak n'est inclus.
