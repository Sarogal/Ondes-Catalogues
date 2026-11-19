# P’tites Ondes — Proposition de catégorie « Atelier sensoriel »

**19 novembre 2026 — proposition éditoriale isolée, sans activation de la carte.**

## Origine de la demande de classification

L'essai réseau du pilote municipal MPT de Montpellier (PR #426) a lu
un index réel de **24 URL** et un échantillon contrôlé de **3 fiches**.
Après filtrage des séances déjà commencées, **2 séances futures** ont
été extraites mais restaient non classées dans les **13 types
non musicaux expérimentaux**.

L'examen du gabarit de page a identifié explicitement des ateliers
sensoriels pour bébés ou familles, notamment le thème « snoezelen ».
Il serait incorrect de les classer automatiquement comme ateliers créatifs
ou activités sportives simplement pour faire monter le compteur.

## Proposition

Ajouter **un quatorzième type familial** :

- ID : `atelier-sensoriel`
- Libellé : `Atelier sensoriel`
- Facette : `atelier`
- Détection **uniquement** par les formulations explicites :
  `snoezelen`, `atelier sensoriel`, `éveil sensoriel`,
  `expérience sensorielle` ou `espace sensoriel`.

Les intitulés génériques « atelier bébé », « espace famille » ou
« détente » ne sont pas considérés comme preuves de ce thème. Les
expressions combinant un sujet sensoriel et la musique restent dans
le chemin musical existant ou en attente de revue, sans requalification
forcée. Les titres ambigus cumulant plusieurs catégories non musicales
demeurent refusés.

La catégorisation d'un titre n'établit **rien** concernant l'âge,
le lieu, le tarif, l'inscription, la date ou le droit de reproduction.
Le contrôle des séances adultes et des événements expirés est inchangé.

## Tests et chaîne de publication

Tests spécifiques pour les intitulés explicites, l'isolement des
genres musicaux, les ambiguïtés, les quatre catégories historiques
invariantes et la conservation des droits de publication à zéro.

La branche est **empilée sur la PR #426**, encore non fusionnée.
Aucune collecte automatique, aucun nouveau droit de publisher,
aucune écriture du catalogue ou d'Infomaniak.

**Attention à l'interface :** avant tout déploiement, le futur filtre
de la carte devra gérer ce nouvel ID de manière cohérente ; un test
d'affichage utilisateur devra vérifier le libellé et la facette. La PR
ne modifie ni HTML ni JavaScript du site hébergé.

L'acceptation structurelle d'une proposition ne devient jamais une
publication : preuves d'institution/organisateur, séance, public,
lieu et GPS, droits et anti-doublons sont toujours requis.
