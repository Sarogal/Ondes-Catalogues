# P'tites Ondes — Fiches factuelles originales : prévalidation des droits

**19 novembre 2026 · développement isolé · aucune publication.**

## Problème démontré

Le module \`scripts/ptitesondes_candidate_promotion.py\` actuellement en \`main\`
demande un collecteur \`opendatasoft-index\` ou \`openagenda-v2\`, un UID OA et
une URL \`openagenda.com\` dans \`permitted()\`. Un événement d'une page HTML
municipale, même correctement vérifié, est donc inéligible à ce publisher.
Il serait incorrect de remplacer simplement cette validation par « toute URL HTTPS ».

Les sondes HTML de #420 → #457 et la qualification familiale de #461 ne
produisent que des diagnostics ; elles ne confèrent **aucune** autorisation.

## Voie développée dans cette PR

\`scripts/ptitesondes_factual_reuse_preflight.py\` propose une **fiche
factuelle originale pour revue privée**, uniquement après preuve d'une séance
exacte sur une page officielle épinglée, admission explicite d'enfants ou de
familles, catégorie non musicale connue et conditions d'accès suffisamment
lisibles. Les tarifs et inscriptions absents restent « non précisés ».

Le brouillon utilise un texte généré exclusivement à partir des faits
confirmés (type, date, heure, lieu, ville, public, âge si déclaré, état de
tarif et de réservation). Il **ne réutilise jamais** la prose descriptive
du site, les affiches ou les photographies. L'intitulé officiel est retenu
séparément pour l'identité et la déduplication, pas dans le texte narratif.
Aucune image téléchargée.

La sortie contient \`safe_to_publish=false\`, \`rights_reviewed=false\`,
\`publication_ready=false\` et \`publisher_connected=false\`.
Le pipeline de diagnostic conserve **uniquement les compteurs anonymes** :
aucun brouillon, URL, organisateur ou événement n'est écrit dans les journaux
Actions. Le fichier ne se connecte pas au publisher ni au backlog privé.

### OpenAgenda, droits à l'événement

Un second contrôle diagnostique examine \`rights.license\`,
\`rights.licensor\` et \`updatedAt\` sur **l'événement exact**, après preuve
structurelle de source OpenAgenda API v2. L'identifiant \`etalab-2.0\` n'est
reconnu comme *déclaration* que lorsque le nom, l'URL officielle de licence
et la date d'actualisation concordent. Cela ne prouve ni que le concédant
est légitime, ni que les images sont réutilisables, ni que la mention
d'attribution est affichée dans notre application.

Documentation officielle : https://developers.openagenda.com/licence/

### Limite juridique essentielle

La collecte de faits isolés et leur reformulation ne rendent pas
automatiquement licites une extraction substantielle ou une réutilisation
systématique d'une base de données protégée, ni des restrictions applicables
à certaines sources. La branche *facts only* **n'accorde aucun droit** sans
une politique de source / base de données vérifiée séparément ; une page
publique n'est pas présumée sous Licence Ouverte.

Le droit français distingue notamment les informations publiques
réutilisables des contenus soumis aux droits de tiers :
https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000031366350/LEGISCTA000032255212/2026-02-05

## Tests et pilotage

Tests synthétiques adversariaux : URL officielle usurpée, mauvaise séance,
entrée adulte seule, âge absent, âge déclaré, public mixte, conditions
d'accès contradictoires, carte d'adhésion obligatoire, tarif inconnu,
reprise prohibée de description/visuels, fausse mention de licence HTML,
licence d'agenda substituée à celle de l'événement, mauvais concédant
et date de mise à jour absente. Le diagnostic HTML réel est borné et
reste strictement en lecture seule.

## Intégration future : un routeur d'admission, pas un assouplissement

La prochaine étape doit créer **un circuit d'admission distinct** pour
les événements HTML institutionnels ayant :
1. un index et une fiche officiels épinglés indépendamment de la proposition ;
2. une séance exacte, un lieu et un GPS vérifiés sans données GPS du candidat ;
3. un public familial confirmé (âge absent autorisé si schéma compatible) ;
4. des conditions d'accès non contradictoires, sans promesse de gratuité ;
5. une **politique réutilisation d'origine / base vérifiée par source**, et
   aucune prose ou image tierce reproduite ;
6. un dédoublonnage strict sur l'identité, la séance et le catalogue public ;
7. une adaptation explicite aux validations du publisher et à son schéma.

La politique de droits peut être enregistrée **par source vérifiée**, sans
exiger une adaptation de code à chaque événement. Aucun résultat de
\`prepare_private_html_factual_draft()\` ne peut lui-même être utilisé comme
jeton de publication. Ne pas recopier aveuglément un booléen \`reviewed\`
fourni par un collector.

**Ce développement n'intègre, ne fusionne ni ne publie rien.** Les PR
de la chaîne HTML sont empilées et doivent faire l'objet d'une revue
des dépendances avant fusion. Infomaniak inchangé.
