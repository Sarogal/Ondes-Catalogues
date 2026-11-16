# P’tites Ondes — vérification d'une décision éditoriale privée

**16 novembre 2026 — code isolé en DRAFT. Aucun accord de publication, aucun patch, aucun déclenchement privé.**

## Pourquoi

Un fichier de collecteur mentionnant « approved: true » ne peut pas approuver
sa propre découverte. Cette branche ajoute un contrôleur indépendant de la
présence d'une **décision humaine explicite**, lue depuis l'API GitHub du
dépôt privé. Le code est public, les dossiers et preuves restent privés.

La décision authentifiée constitue **uniquement un prérequis éditorial** :
le contrôleur ne crée aucune fiche publiable, ne modifie aucun catalogue
et ne fait pas passer le rapport de #325 en « publication_ready ».

## Manifestation de décision

Chaque séance dispose d'un manifeste *privé* de version
ptitesondes.municipal_private_approval_request.v1, contenant :

- Identifiant stable municipal-gosier-ID-YYYY-MM-DD
- Numéro d'une PR **du dépôt privé Sarogal/PtitesOndes**
- SHA exact de la tête de cette PR
- Date et lien officiel de l'occurrence
- SHA-256 canonique de la proposition privée, des conditions d'accès,
  des données du catalogue et SHA-256 du HTML de la fiche municipale

Le module refuse le manifeste si **un seul octet de preuve pertinent a
changé** : il recalcule les empreintes des documents réels reçus. Le
prévalidateur municipal indépendant de #325 vérifie séparément les
informations du site source.

## Comment un humain pourra exprimer son accord

Après création d'une PR privée contenant le manifeste de preuve, **le
propriétaire devra lui-même**, via son compte GitHub, poster un commentaire
strictement égal à la ligne générée par decision_line(manifest, APPROVE).
Le texte commence par PTITESONDES-MUNICIPAL-APPROVE-V1 et lie un ID
d'occurrence, un SHA-256 de manifeste et un commit exact.

Pour révoquer, le même propriétaire peut publier la variante REVOKE.
La décision authentifiée la plus récente l'emporte.

Le contrôleur lit **uniquement** les commentaires d'une PR GitHub privée,
vérifie l'identité du compte Sarogal de type User, le statut OWNER, les
droits admin ou maintain retournés par l'API GitHub et le SHA exact de la PR.
Une réponse manquante, refusée ou incohérente bloque toute décision.

ATTENTION : une identité GitHub prouve le compte authentifié, pas le
périphérique ni la méthode UI/API. Ne jamais donner le jeton privé à un
collecteur non fiable. Aucun commentaire d'accord n'est produit
automatiquement par ce code.

## Interface technique

Module : scripts/ptitesondes_municipal_human_decision.py

Entrées : manifeste privé, proposition et conditions privées, HTML officiel,
catalogue public ; lecture des métadonnées PR / commentaires / permissions
avec PRIVATE_INTAKE_READ_TOKEN à travers le GitHub API HTTPS certifié.

Rapport privé : indicateur human_approval_evidence, last_decision et
toujours publication_ready=false, approval_granted_to_publisher=false,
public_writes=0. Résumé console limité aux indicateurs agrégés.

Tests adversariaux : usurpation du propriétaire, bot, faux droits,
révocation tardive, changement du commit, PR déplacée, catalogue modifié,
source HTML modifiée, prix falsifié, manifestes autovalidés, pagination
incomplète et jeton absent.

## Reste bloqué

- **Pas de dossier réel approuvé à ce jour**. Les neuf séances du Gosier
  restent à relire et approuver individuellement.
- Pas de PR privée d'approbation créée automatiquement.
- Pas de jonction active entre ce contrôleur et le synchroniseur public.
- Le schéma de catégories et l'affichage v173 restent des PR distinctes.
- Tout déploiement ou fusion demeure subordonné à validation explicite.

Cette implémentation ne remet pas en question les agendas nationaux
OpenAgenda ni les événements musicaux historiques.
