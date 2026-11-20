# Grosses Ondes — qualification radio : preuve de continuité (laboratoire du 20/11/2026)

## Portée
Branche isolée dérivée de la PR publique #474. Aucun changement à l'application, au catalogue signé, aux identifiants ou aux flux/logos existants. RADIO BOB! et ses stations sont intégralement conservées.

## Deux niveaux de vérification
1. Sondage court : 512 octets, signature audio, HTTP/ICY, DNS validé et IP publique épinglée, TLS, redirections et M3U/PLS simples.
2. Sondage de continuité sur option explicite --allow-network --extended-continuity : lorsque la réponse HTTP 200 comporte un en-tête audio reconnu, observer plusieurs lectures de la MÊME connexion pendant au moins 6 secondes et au moins 4096 octets.

Budgets : au plus 10 secondes de mesure, 512 KiB et 1024 lectures; les temporisations de connexion/lecture peuvent ajouter du temps réel avant le retour. La requête longue n'utilise pas Range. Une réponse dotée de Content-Length est classée non confirmée, pour éviter de confondre un fichier audio fini avec un flux.

Un résultat continuityEvidence.state=transport_sustained prouve seulement que des octets ont continué d'arriver. Cela ne confirme PAS leur décodage, la musique, ni un flux live plutôt qu'un transfert artificiellement lent.

## Barrières conservées
- publicationAllowed=false et technicalVerifiedCount=0 dans tous les rapports.
- Aucun publisher, aucune suppression de station en cas de panne, aucune mutation du catalogue historique ni des logos.
- HLS toujours en attente : aucun segment ni variante téléchargé aveuglément; M3U/PLS multi-cibles restent ambigus.
- HTML, JSON, XML et ID3 incomplet ou malformé exclus de l'évidence audio.
- Toutes les URL suivies restent soumises à validation anti-SSRF, DNS et connexion IP épinglée, protection TLS et budget de redirections.

## À compléter avant une publication automatisée
1. Tester manuellement sur davantage de flux réels, retenir les verdicts et les requalifier sur plusieurs journées.
2. Démontrer le décodage borné des trames MP3, AAC, Ogg/Vorbis/Opus, FLAC et des variantes courantes; sécuriser l'analyse HLS.
3. Vérifier l'identité des radios, les alias, les 27 UUID non encore réconciliés et la stabilité sans fusion abusive.
4. Tester le catalogue signé, les favoris, les logos SHA, Android Auto, la bascule arrière et le mode hors ligne.
5. Obtenir l'autorisation expresse avant fusion, cron actif sur la branche par défaut ou production.

## Utilisation
Tests : python -m unittest discover -s radio-catalog-lab/tools -p 'test_radio_stream_continuity_evidence.py' -v
Sondage réseau : python radio-catalog-lab/tools/radio_stream_technical_probe.py --discovery candidates.json --output technical-probes.json --limit 2 --allow-network --extended-continuity
Le workflow sur branche de laboratoire exécute les tests à chaque push. Les sondages étendus sont facultatifs en déclenchement manuel (run_stream_probes=true, deux échantillons), et prévus par la programmation quotidienne (cinq échantillons). Le cron reste dormant tant que le workflow n'est pas sur la branche par défaut. Le registre sépare désormais audioEvidenceDates et sustainedTransportDates, sans certification ni publication; la reprise effective du registre entre exécutions doit encore être validée en conditions réelles.

## Avancement du 20 novembre — preuve structurelle MPEG/AAC

Le module radio_stream_frame_chain.py analyse au plus 64 KiB des octets reçus par la même connexion, sans les écrire dans les rapports, et exige trois trames entières consécutives : MPEG audio (couches I/II/III) ou AAC ADTS. Les en-têtes, les longueurs de trames et la cohérence des paramètres sont contrôlés. Cette vérification est structurelle, **pas** un décodage PCM ni une preuve que le contenu est un programme radio en direct.

Le registre radio_stream_recheck_ledger.py conserve maintenant trois familles de dates indépendantes : audioEvidenceDates (en-tête reconnu), sustainedTransportDates (octets maintenus au moins six secondes) et frameChainDates (chaîne de trames lors d'un transport soutenu). Aucune de ces observations ne met technicalQualified ou publicationAllowed à vrai, même après plusieurs jours.

Validation générale : run #44724323883, 152 tests Python réussis (37 + 11 + 40 + 15 + 3 + 25 + 10 + 11). La suite précédente #44723950078 avait 146 tests. Les chiffres ne signifient pas 152 flux contrôlés.

Pilote réseau et conservation des preuves : run #44724530213, SUCCESS. Sur 13 requêtes Radio Browser, 383 UUID distincts dans les réponses (sans rapprochement avec le catalogue), cinq URLs contrôlées ; trois en-têtes audio reconnus, trois transmissions soutenues, trois chaînes de trames cohérentes, deux cas audio_mime_only et zéro admission. Le registre a conservé trois observations frameChainDates pour cette première journée, sans qualification finale ni publication.

Le prochain verrou est le **décodage réel**, avec validation par un décodeur audio isolé, limites de CPU, mémoire et durée, et gestion générique des variantes Ogg/Opus/Vorbis, FLAC, HLS et métadonnées ICY. Il faudra ensuite des contrôles sur plusieurs jours réels et une réconciliation complète avant l'intégration au catalogue signé.
