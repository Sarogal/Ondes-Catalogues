# P'tites Ondes — contrat de file privée HTML, lot isolé du 20/11/2026

## Pourquoi une file distincte

Le backlog privé existant est `automation-intake/ptitesondes/backlog.json`.
Son collecteur `automation/outings_intake.py` rapproche par URL de source,
titre, lieu et date **sans horaire** : deux séances de même jour risquent
donc d'être confondues. Ne pas modifier ce format ni les 437 propositions
vérifiées lors de la reprise.

Le futur fichier privé proposé est
`automation-intake/ptitesondes/html-review-candidates.json`, contenant
une liste de dossiers `ptitesondes.html_private_review_queue.v1`.
Ce fichier **n'est pas créé** par cette PR. Aucun runner n'y écrit encore. En revanche, le funnel sait maintenant transmettre ses dossiers **en mémoire** à la réconciliation par une option privée, sans publier leur contenu.

## Ce que fait le composant

`scripts/ptitesondes_nonmusical_private_queue_handoff.py` fournit une
réconciliation pure en mémoire. Pour chaque séance, elle **rejoue**
`route_nonmusical_html_session` et
`prepare_private_html_factual_draft` avec une page et des références
institutionnelles épinglées par le *runner de confiance*.

`prepare_private_html_review_handoff()` raccorde l'adaptateur HTML institutionnel et le contrat de file **en mémoire**, sans créer de fichier. Le funnel propose une option `private_review_sink` absente par défaut et n'émet que les séances dont les faits exacts ont déjà été corroborés. Un second passage par le routeur et le préparateur factuel protège la file contre une simple déclaration du collecteur.

Elle ne fait confiance ni à un `approved` fourni par le collecteur ni à
un rapport de route fourni comme entrée. Elle conserve le titre factuel,
la source exacte HTTPS, la date et l'horaire local strict, la catégorie,
la ville, le lieu, le code de blocage et la prochaine action privée.
L'identité SHA-256 tient compte **de l'horaire**, et deux sources donnant
la même séance restent distinctes et signalées pour vérification.
Les absences de sources n'effacent jamais les dossiers existants.

Les motifs de défaut de registre / fraîcheur ont une date de nouvelle
tentative indicative (J+2). Les cas de droits en attente et de
corroboration manquante restent en attente de décision ou de nouvelle
preuve. Ni tranche d'âge ni tarif ne sont inventés.

## Limites et chaîne encore manquante

Cette PR n'est **pas** le raccordement d'un runner en production :
- La sortie privée en mémoire existe désormais dans le funnel, mais son
  activation exige un runner authentifié et des registres indépendants.
  Les rapports publics continuent de ne contenir que des compteurs.
- Il faut intégrer la réconciliation au cycle existant avec une écriture
  exclusivement sur `automation/ptitesondes-intake`, sous concurrence
  protégée et sans jamais afficher la file ou les pages HTML dans les
  journaux d'un runner public.
- Il faudra une seconde vérification en direct de l'organisateur, du GPS,
  des règles de réutilisation de la source/base, du catalogue servi et des
  collisions avant de concevoir un publisher non musical append-only.
- Les sources légalement en attente restent bloquées. La provenance
  institutionnelle ne vaut pas licence.
- La simulation de schéma #479 reste distincte du publisher musical.
- Cette file ne se substitue pas aux `patch-AAAA-MM-JJ.json` privés et
  ne contient aucune commande de publication.

## Confidentialité et sûreté

La réponse de l'algorithme possède une `queue` strictement **privée** et
un `report` à compteurs fixes seulement ; seule la seconde est
autorisée en journaux publics. Il n'y a ni clé, ni HTTP, ni fichier écrit,
ni patch, ni publication dans ce composant.

PR volontairement en brouillon, empilée sur #479. Ne pas fusionner ni
modifier GitHub Pages, Infomaniak ou le dépôt privé sans autorisation.
