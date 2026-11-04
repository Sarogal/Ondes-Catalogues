# Preuve organisateur complémentaire — spectacles jeunesse

## Cas traité le 4 novembre 2026

Deux événements du Théâtre de Jeanne à Nantes ont été découverts via
l'index public OpenDataSoft d'OpenAgenda. Leur page OpenAgenda renvoie un
squelette « Loading... » au lecteur HTML du synchroniseur : il manque donc
la preuve indépendante de dates et horaires.

Le module `scripts/official_organizer_proof.py` maintient une liste
**explicite et auditée** des URL OpenAgenda compatibles avec une URL de
programme **directement publiée par l'organisateur** :

- `Quand le chat n'est pas là… ça part en LIVE !`
  - Organisateur : https://www.theatre-jeanne.com/spectacle/quand-le-chat-nest-pas-laca-part-en-live/2027-01-13/
  - Séances possibles : 13 janvier 2027 à 14 h 30, 14 janvier à 10 h 30,
    20 janvier à 14 h 30
- `Un animal, des amis mots`
  - Organisateur : https://www.theatre-jeanne.com/spectacle/un-animal-des-amis-mots/2027-02-10/
  - Séances possibles : 10 et 17 février 2027 à 14 h 30, 14 février à 15 h

Ces horaires restent **des contraintes de validation**, pas des données
publiées de manière inconditionnelle. À chaque contrôle, la page HTML
organisateur est **relue en direct** et doit confirmer l'année 2027,
l'intitulé, la salle, Nantes, le public jeunesse, la période ET le schéma
d'horaires du jour exact. Toute correction, annulation, 403, 404, 429,
date modifiée, absence de texte, incohérence d'année ou redirection
inattendue bloque la validation.

L'index OpenAgenda doit **en parallèle** exposer cet événement par son
UID, sa date exacte, son horaire, son statut programmé, son URL canonique et
ses coordonnées concordantes avec le registre de lieu indépendant.

Ce contrôle ne retire aucune protection du synchroniseur : identifiants
historiques intacts, pas de fausse période continue, catégories et schémas
stricts, pas de champ âge/tarif inventé, aucune correction automatique des
fiches publiées.

## Évolutivité

Pour ajouter un nouvel organisateur, effectuer un audit manuel de ses pages
officielles et de ses conditions d'accès. Mettre à jour `PROGRAMS` avec
l'URL canonique OpenAgenda exacte, l'URL organisateur vérifiée, le titre,
le lieu, la catégorie et une **règle de séance explicite**. Ajouter les
tests des dates rejetées, du calendrier exact, des horaires, des reports
et du comportement en panne réseau. Aucune recherche arbitraire ni
redirection cross-domain n'est autorisée pendant le contrôle.

## Tests

`python -m unittest discover -s tests -p 'test_official_organizer_proof.py' -v`

La politique de publication ne change pas : la prévalidation reste
sans commit public, et `merge_policy.merge` revérifie indépendamment
les mêmes preuves avant tout ajout.
