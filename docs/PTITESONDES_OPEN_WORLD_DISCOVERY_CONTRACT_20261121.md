# P’tites Ondes — Contrat d’architecture : découverte ouverte, publication prouvée

**21 novembre 2026 — aucun déploiement**

## Invariant non négociable

**Une ville, un lieu, un organisateur, un agenda, un fournisseur, un format culturel ou une formulation non encore connus ne doivent jamais être refusés à la découverte pour la seule raison qu’ils n’apparaissent pas dans un inventaire préexistant.**

Les registres de lieux, les manifestes d’agendas et les lexiques de mots-clés servent à accélérer la recherche, pas à définir une liste exhaustive des sources autorisées.

La découverte n’est **pas** une autorisation de publication. Un fait non prouvé reste en attente.

## Tableau des distinctions

| Objet | Découverte | Admission et publication |
|---|---|---|
| Commune, village, ville | Ouverts à toute nouvelle localité française | Pays et territoire contrôlés |
| Lieu, place, rue sans numéro | Aucun registre antérieur ni numéro exigés | Identité et coordonnées exactes vérifiées indépendamment |
| Agenda OpenAgenda | Recherche UID/slug indépendante du manifeste | Lien institutionnel indépendant et événement original |
| Autre fournisseur | Nouvel adaptateur par contrat de provenance | Producteur, origine et droits vérifiés |
| Organisateur, hôte ou billetterie | Inconnu = enquête, jamais exclusion par liste | Domaine officiel corroboré, HTTPS et réseau sécurisé |
| Activité et vocabulaire | Reconnaissance rapide ou file privée de recherche ouverte | Concert, musique, éveil sonore, conte, lecture et spectacle jeunesse ; ni simple goûter ni loisir générique |
| Séances | Pas de seuil arbitraire 4/20 ; pagination complète sur les lots | Toutes les dates et tous les horaires indépendamment prouvés |
| Géographie | Métropole, Corse et tous les territoires français | Fuseau exact et cohérence physique ; pas de point inventé |
| Droits, âge, réservation | Informations manquantes = recherche | Contradiction, interdiction ou annulation = retenue ou rejet |
| Sécurité | Aucune autorisation implicite par HTTPS | URL sûre, preuves indépendantes, pas de SSRF, pas de secret exposé |

## Développement déjà proposé en PR brouillon

- #576 : route directe OA si absence ODS exacte et avérée ; panne ODS = maintien en attente.
- #577 : proposition schema-compatible issue de nouveaux lieux et de places sans numéros prouvés indépendamment ; non publiable.
- #579 : découverte d’agendas inconnus à partir du slug, contre-vérification de l’UID, manifeste pouvant être vide en recherche privée.
- #580 : recherche directe OA sans ODS, lieux et villes inconnus admis à la recherche, couverture de tous les territoires français. Activités non reconnues conservées dans une file de recherche privée distincte des event_leads admissibles.

## Verrous encore présents, à résoudre sans réduction de sécurité

1. **Catégories historiques** : merge_policy.valid refuse une catégorie absente du catalogue de référence. Une nouvelle famille éditoriale exige également l’affichage dans le frontend. Ne pas diffuser une catégorie incompatible.
2. **Domaines officiels** : proof.py.HOSTS conserve une liste historique fermée. La remplacer par une preuve de provenance externe vérifiée (DILA municipal, institution, organisateur indépendant), pas par la confiance en tout HTTPS.
3. **Agenda vérifié** : review_missing_mirror_source dépend d’un curated_agenda. La preuve institutionnelle doit pouvoir être dérivée dynamiquement sans manifeste prérempli.
4. **Organisateurs privés et partenaires tiers** : la preuve DILA des communes ne suffit pas. Trouver d’autres mécanismes de provenance indépendante, sans whitelist de partenaires.
5. **Nouveaux collecteurs** : l’admission historique reconnaît OA/ODS. Faire évoluer le contrat vers des assertions de source + preuves d’origine, sans accepter un collecteur auto-déclaré comme officiel.
6. **Sessions scolaires** : conserver les exceptions de protection existantes tant qu’une alternative générique de même rigueur n’est pas éprouvée.
7. **Autonomie réelle** : modes opt-in et CI verte ne prouvent pas une veille opérationnelle quotidienne. Mesurer le traitement de vraies dates et la mise à jour de la carte avant toute annonce.

## Anti-régressions obligatoires

- Ville/lieu/organisateur nouveau, place ou rue sans numéro ; découverte non bloquée.
- Manifeste vide, agenda inconnu, événement absent d’OpenDataSoft ; recherche possible sans appui sur ODS.
- Métropole, Corse et territoires ultramarins français ; fuseaux locaux et GPS exacts.
- Formulation artistique jeunesse inconnue conservée en recherche, sans admission automatique.
- Goûter au parc non admis. Événement scolaire réservé non admis.
- Fausse API, UID incohérent, lieu contradictoire, annulation, URL hostile, preuve forgée : blocage obligatoire.
- Aucune activation de workflow, écriture de production, publication ou exposition de clés.

**État réel :** ces principes commencent à être appliqués au stade de découverte et d’audit, mais le publisher et la provenance universelle ne sont pas encore entièrement refondus. Ce document décrit une exigence et une dette restante, pas une autonomie déjà prouvée.
