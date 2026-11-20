# P'tites Ondes — stockage privé HTML opt-in (20/11/2026)

Ce lot s'empile sur la PR #486 validée et reste en brouillon. Il ne modifie aucune production.

## Implémentation
- scripts/ptitesondes_html_private_queue_cycle.py : récupère les index et séances HTML institutionnels depuis le registre commis, uniquement via les adaptateurs connus. Ni URL de collecteur, ni preuve GPS ou droits fournie par le candidat n'est utilisée pour autoriser une publication.
- File privée cible : automation-intake/ptitesondes/html-review-candidates.json, sans toucher au backlog historique. La clé comprend l'heure exacte, pour distinguer les séances multiples.
- Mode preview : lecture seule. Mode stage : écriture atomique du fichier uniquement dans un checkout local validé du dépôt Sarogal/PtitesOndes sur automation/ptitesondes-intake. Le script ne commite ni ne pousse.
- Pont existant : étape optionnelle désactivée tant que vars.PTITESONDES_HTML_QUEUE n'est pas explicitement fixée à enabled. Aucune variable n'est modifiée par la PR. Le dépôt public n'est jamais destination de push.
- Rapports : compteurs anonymes exclusivement. La file complète est réservée au stockage privé.

## Garanties et limites
- Aucune fusion, aucun déploiement, aucune écriture privée réelle et aucune publication dans cette PR.
- Les droits de la source Maisons pour Tous Montpellier restent pending_source_legal_review : publier reste interdit.
- Le premier adaptateur connu est Montpellier MPT. La couverture nationale exigera des formats HTML réutilisables et de nouveaux registres institutionnels indépendants.
- Le contrôle de fraîcheur du catalogue avant publication ne doit pas se baser uniquement sur updated_at.
- Il manque encore la vérification indépendante d'organisateur, de GPS, de réutilisation, de doublons live et un publisher générique non musical.
- La CI doit vérifier le verrou de branche privée, le verrou de variable, les tests multiséances, les erreurs de source et l'absence de publication.

## Précondition d'activation
Aucune activation de variable, fusion ou modification du site sans autorisation explicite et revue des quatre suites GitHub sur le dernier commit.
