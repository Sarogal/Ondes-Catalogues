# Grosses Ondes — preuves techniques de plusieurs flux par radio (opt-in, non publiant)

**20/11/2026 — laboratoire isolé de la PR #492, sans modification des catalogues ni de la production.**

## Pourquoi

La file Release 1 de la PR #515 peut examiner plusieurs variantes MP3/AAC
pour une même radio et des stations historiques ayant des flux de secours.
Le registre technique historique utilisait uniquement le **UUID Radio Browser**
comme clé de suivi. Si une même station passait du flux A au flux B, il
remplaçait les observations du flux A. Une vérification ultérieure du flux A
ne pouvait donc pas démontrer une stabilité indépendante sur plusieurs jours.

## Modification ciblée

`radio_stream_recheck_ledger.next_evidence_report(...,
retain_stream_variants=True)` conserve un enregistrement distinct par
**(stationuuid, SHA-256 exact de l'URL du flux)**. Les dates de preuve MP3/AAC,
transport prolongé, trames, décodage PCM et leurs indicateurs de répétition
demeurent propres à la variante. Les anciennes preuves ne sont jamais
attribuées à une nouvelle URL. Un échec ou une absence n'efface pas les flux
historiques ni leurs identifiants, et aucune preuve ne délivre un
`technicalQualified=true` ou `publicationAllowed=true`.

La valeur par défaut de la fonction demeure le comportement UUID historique :
les usages existants et la PR #492 ne sont pas basculés implicitement.
Pour la nouvelle chaîne Release 1, l'option CLI
`--retain-stream-variants` active explicitement le mode multi-flux :

```sh
python radio-catalog-lab/tools/radio_stream_recheck_ledger.py \
  --probe /scratch/batch-01-probes.json \
  --previous /scratch/prior-stream-evidence.json \
  --output /scratch/next-stream-evidence.json \
  --retain-stream-variants
```

Le premier passage omet `--previous`. Chaque rapport nouveau doit être
utilisé comme `--previous` du passage suivant. Il n'est pas possible de
revenir au mode UUID simple avec une archive `per_stream`, car une telle
rétrogradation ferait perdre l'identité des variantes. Les archives
historiques simples (y compris celles sans champ `streamHistoryMode`)
peuvent être migrées dans le nouveau mode **sans inventer de preuve**.

Le sondeur réseau existant garde sa limite de 5 flux par appel. Le planificateur
de la PR #515 prépare jusqu'à 8 lots distincts, au plus 40 flux par jour.
Ces lots peuvent être consolidés **séquentiellement et hors ligne** par le
registre multi-flux ; aucun déclenchement automatique n'est effectué ici.

## Contrôles

Le workflow public
`.github/workflows/radio-stream-multivariant-ledger-ci.yml`
valide les tests existants et les nouveaux scénarios synthétiques de
conservation/retour de variantes, migration des anciens rapports et refus
d'une rétrogradation. Les exemples ne contiennent pas de véritables URLs
de stations, aucune clé et aucun octet audio.

**Restent à faire :** exécution des vrais contrôles réseau, persistance durable
des observations, revue éditoriale de chaque identité, raccordement au
catalogue privé, cache des logos, signature Ed25519, vérification Android et
Android Auto. Ne pas fusionner sans validation explicite.
