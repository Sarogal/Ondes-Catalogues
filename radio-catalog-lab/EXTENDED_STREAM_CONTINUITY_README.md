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
