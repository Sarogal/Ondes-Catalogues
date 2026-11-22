# P'tites Ondes — découverte de nouveaux agendas OpenAgenda

**Prévisualisation uniquement — aucun cron, aucune admission, aucune publication.**

## Pourquoi consulter au-delà des 16 agendas existants ?

Les UID d'agendas configurés dans le dépôt privé ne constituent pas une liste exhaustive. Une piste OpenDataSoft du backlog peut appartenir à un agenda inédit. Le pipeline de découverte doit consulter cet agenda, sans le considérer automatiquement comme une source autorisée.

Le module scripts/ptitesondes_dynamic_oa_agenda_discovery.py lit un **snapshot privé** du backlog et recherche les UID d'événements OpenDataSoft valables, quelle que soit la commune, le nom du lieu ou l'activité. Il traite au maximum 40 UID uniques par lot. Chaque UID de l'agenda nouvellement rencontré est recoupé via trois lectures :

1. Fiche ODS exacte : UID + URL canonique + lieu + commune + agenda d'origine.
2. Fiche publique OpenAgenda v2 de cet agenda : UID et slug correspondants.
3. Fiche publique OpenAgenda v2 de l'événement exact : UID, statut publié, lieu physique et commune concordants.

Le résultat est une **liste privée d'agendas à examiner**, pas une whitelist de publication. Les droits, la responsabilité éditoriale de l'organisateur, l'âge, les horaires et la localisation indépendante restent à vérifier pour chaque séance. La collecte peut examiner des agendas mixtes sans pour autant admettre toutes leurs activités ; la règle éditoriale reste musique, contes, histoires et spectacles jeune public.

## Exécution privée (non activée ici)

Le dépôt public de cette branche et les deux fichiers d'entrée doivent être dans des checkouts séparés. Le dossier de sortie doit être privé, hors du dépôt public et avec permissions 0700. La clé OPENAGENDA_READ_KEY est une clé OpenAgenda **publique de lecture**, jamais un secret administrateur.

Vérification hors réseau :

    python scripts/ptitesondes_dynamic_oa_agenda_discovery.py       --backlog /espace-prive/automation-intake/ptitesondes/backlog.json       --private-source-config /espace-prive/automation/sources.json       --output-private-report /espace-prive/rapports/sources-0.json       --day 2026-11-20 --batch-index 0

La même commande avec --live-probe effectue les lectures ODS et OA. Chaque lot doit recevoir un nouveau fichier privé. La sortie standard est **uniquement chiffrée** ; le rapport détaillé contenant les UID/slug ne doit jamais être versé dans les artifacts GitHub Actions publics, les journaux ou les dépôts publics.

## Limites assumées

- Aucun run réseau réel avec la clé OA n'a été lancé depuis ce chantier.
- Ce module ne découvre pour l'instant que les agendas signalés par les pistes ODS déjà collectées ; il ne constitue pas un inventaire exhaustif de tous les agendas français.
- Une source découverte n'est pas une source homologuée, et une fiche d'agenda ne vérifie pas chaque séance.
- La planification, la persistance privée des découvertes, le raccordement au pipeline de qualification et la surveillance des nouveaux agendas doivent faire l'objet d'une intégration séparée et autorisée.
- Les sorties hors périmètre radio-enfants restent exclues même si leur agenda est découvert.

**Aucun effet sur les catalogues publics, les workflows de production, Infomaniak ou Grosses Ondes.**
