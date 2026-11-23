# Grosses Ondes — audit des 304 radios actives (23 novembre 2026)

**Source :** catalogue signé TEST v6 ; SHA-256 `40215a58967a8b7a83b322c9f02645a9bc2bf319385442e5d89277e0b0d6d861`. Cette branche ne change ni le pointeur TEST actif, ni main, ni le Play Store.

## Bilan vérifié

- **304 radios actives**, 11 fiches inactives, 5 redirections de précédentes fusions.
- **185 radios actives avec descripteur de logo** ; **119 sans logo** (39,1 %).
- **98 empreintes SHA distinctes** pour 185 logos actifs : plusieurs programmes partagent un visuel de marque.
- **13 groupes de doublons très étayés**, avec **19 fiches excédentaires** si on conserve une station par programme.
- **4 autres groupes à confirmer**, représentant jusqu’à **4 fiches excédentaires** supplémentaires.
- Absence de doublon parfait par URL strictement identique ; de nombreux doublons diffèrent par codec, protocole, port ou suffixe de lecture.

## Doublons à forte confiance (aucune fusion encore effectuée)

| Programme | Fiches et noms | Justification |
|---|---|---|
| Radio BOB! Metalcore | `000003` DrGnu - Metalcore 1 ; `000139` RadioBOB Metalcore (64 kbps AAC) ; `000290` RADIO BOB! BOB's metalcore | Même canal /metalcore chez RADIO BOB! ; qualités MP3 et AAC |
| Radio BOB! Metal | `000013` RadioBOB Metal (64 kbps AAC) ; `000159` RADIO BOB! BOBs Metal ; `000253` DrGnu - Metal 1 | Même canal /bob-metal chez RADIO BOB! ; qualités MP3 et AAC |
| Radio BOB! 2000er Rock | `000106` DrGnu - 20th Century Rock ; `000131` RADIO BOB! 2000er Rock [64 kbit/s AAC] | Même canal /2000er chez RADIO BOB! ; le nom DrGnu est trompeur |
| Radio BOB! Harte Saite | `000158` RADIO BOB! BOBs Harte Saite ; `000238` Radio BOB! Harte Saite | Même canal /bob-hartesaite/mp3-192 ; HTTP contre HTTPS |
| Radio BOB! Metallica | `000250` RadioBOB Metallica (64 kbps AAC) ; `000276` DrGnu - Metallica | Même canal /metallica chez RADIO BOB! ; MP3 et AAC |
| Radio Caprice Thrash Heavy Metal | `000049` RadCap - Thrash Heavy Metal ; `000231` Thrash Heavy Metal - Caprice Radio | Même canal /thrashheavy ; ports 8004 et 8000 |
| Radio Caprice Nu Metal | `000061` Radio Caprice - Nu Metal ; `000300` RadCap - Nu Metal | Même canal /numetal ; ports 8002 et 8000/8004 |
| Radio Caprice Rock Ballads | `000072` Radio Caprice - Rock / Metal Ballads ; `000119` Radio Caprice - Rock Ballads | Même canal /rockballads ; ports 8002 et 8000 |
| Radio Caprice Melodic Metalcore | `000112` Radio Caprice - Melodic Metalcore ; `000288` RadCap - Melodic Metalcore | Même canal /melodicmetalcore ; ports 8002 et 8004 |
| SomaFM Metal Detector | `000060` SomaFM Metal Detector (32k AAC) ; `000097` SomaFM Metal Detector (64k AAC) ; `000149` SomaFM Metal Detector (128k AAC) ; `000185` SomaFM Metal Detector (128k MP3) | Même programme officiel ; AAC 32/64/128 et MP3 128 |
| FluxFM MetalFM | `000143` Gnu Radio - Metal FM ; `000177` FluxFM - MetalFM ; `000208` Metal FM ; `000269` DrGnu - Metal 2 | Même identifiant flx-metalfm-mp3-320-9154971 sur 3 fiches, plus /metalfm/mp3-128 |
| ROCK ANTENNE Heavy Metal | `000073` ROCKANTENNE Heavy Metal (64 kbps AAC) ; `000148` Rock Antenne Heavy Metal | Même canal heavy-metal ; AAC et MP3 |
| RTBF Classic 21 Metal | `000105` Classic 21 Metal ; `000150` RTBF Classic 21 - Metal | Même chaîne officielle Classic 21 Metal ; AAC et MP3 |

**Sous-total :** 13 groupes ; 32 fiches actives concernées ; 19 fiches potentiellement fusionnables. Les URL MP3/AAC utiles doivent être conservées sous une seule station et chaque ancien GO ID / UUID doit rester redirigé vers le survivant.

## Doublons probables à vérifier avant toute fusion

| Programme | Fiches et noms | Incertitude |
|---|---|---|
| Radio Caprice Funeral Doom | `000027` RadCap - Funeral Doom Metal ; `000047` Radio Caprice - Funeral Doom Metal | Même nom, port 9085 et chemin /funeraldoom ; vérifier le programme |
| ChroniX Aggression | `000123` ChroniX AGGRESSION ; `000293` ChroniX Radio - Aggression | Même nom et diffuseur, serveurs différents ; vérifier la diffusion |
| METAL ONLY | `000035` METAL ONLY - http://www.metal-only.de,METAL ONLY - http://www.metal-only.de - 24h Black Death Heavy Metal Rock und mehr! ; `000254` METAL ONLY - https://www.metal-only.de,METAL ONLY - http://www.metal-only.de - 24h Black Death Heavy Metal Rock und mehr! | Même intitulé et hôtes metal-only / metalonly.sp.radio.fm ; confirmer |
| metalrock.fm | `000098` metalrock.fm ; `000259` metal rock radio | Même domaine et même hôte torontocast, ports 2820 et 2800 ; confirmer |

**Ne pas fusionner sur la seule similitude du nom :** RADIO BOB! Wacken et RauteMusik Wacken, les deux radios Exclusively Led Zeppelin (dont « Only Hits »), Radio Regenbogen et Regenbogen 2, ainsi que les différents canaux Rock Antenne et Radio Caprice de genres voisins. Ce sont des programmes distincts jusqu’à preuve contraire.

## Liste exhaustive : 119 radios actives sans descripteur de logo

Les fiches suivantes ont `logo = null` dans la v6. Les 185 fiches disposant d’une URL de logo ne sont pas garanties comme actuellement joignables sur le réseau ; ce contrôle concerne l’absence d’une **référence signée**.

### Exclusively — 5 radio(s)

| Identifiant | Nom affiché |
|---|---|
| `go-station-000204` | Exclusively Led Zeppelin - Only Hits |
| `go-station-000272` | Exclusively Deep Purple |
| `go-station-000274` | Exclusively Led Zeppelin |
| `go-station-000299` | Exclusively Iron Maiden |
| `go-station-000311` | Exclusively Ramones |

### laut.fm — 14 radio(s)

| Identifiant | Nom affiché |
|---|---|
| `go-station-000040` | RADIO NARCAN |
| `go-station-000056` | Altrockmetal-Radiogirls |
| `go-station-000066` | LAGERFEUERMETAL |
| `go-station-000070` | laut.fm - Endzeit FM |
| `go-station-000075` | ProgAlley |
| `go-station-000078` | ODINSMETALROCKCLUB |
| `go-station-000082` | laut.fm - Shamanic Tunes |
| `go-station-000124` | Bavarias Rock Ballads |
| `go-station-000127` | DJ 666 Geordieblackcore |
| `go-station-000135` | STREETFIGHTER |
| `go-station-000162` | Radio todamax |
| `go-station-000166` | core-mix |
| `go-station-000169` | Ultra Dark Radio |
| `go-station-000315` | PUNKRATZ |

### Radio Maximum — 3 radio(s)

| Identifiant | Nom affiché |
|---|---|
| `go-station-000002` | Radio Maximum - Supernova |
| `go-station-000041` | Radio Maximum - Heavy 80s |
| `go-station-000263` | Radio Maximum - Heavy Monday |

### Radio Metal On — 3 radio(s)

| Identifiant | Nom affiché |
|---|---|
| `go-station-000024` | Radio Metal On: Toxic |
| `go-station-000046` | Radio Metal On: The Thrasher |
| `go-station-000218` | MetalON - The Heavy |

### RauteMusik — 1 radio(s)

| Identifiant | Nom affiché |
|---|---|
| `go-station-000039` | __SHREDDED__ by RauteMusik (rm.fm) |

### Autres diffuseurs — 93 radio(s)

| Identifiant | Nom affiché |
|---|---|
| `go-station-000006` | Rockaxis Radio |
| `go-station-000014` | Metal Heart |
| `go-station-000017` | ARfm |
| `go-station-000018` | Nuclear Fallout Radio |
| `go-station-000020` | Radio Bizzz |
| `go-station-000028` | X Transmission FM |
| `go-station-000032` | Alternativa by MIX (iHeart Radio) - Online - ACIR Online / iHeart Radio - Ciudad de México |
| `go-station-000035` | METAL ONLY - http://www.metal-only.de,METAL ONLY - http://www.metal-only.de - 24h Black Death Heavy Metal Rock und mehr! |
| `go-station-000038` | РокРадіо Metal |
| `go-station-000042` | The Pit \| NTS |
| `go-station-000062` | Rocker Rádió |
| `go-station-000067` | True Black Metal Radio |
| `go-station-000069` | Power FM - Rock FM |
| `go-station-000071` | Radio-Drachenblut |
| `go-station-000074` | WSOU |
| `go-station-000076` | Szent Korona Rádió |
| `go-station-000081` | BDPST ROCK Rádió (Hi-Fi / Lossless / FLAC) |
| `go-station-000087` | Virgin Radio Rockstar: Guns N' Roses |
| `go-station-000088` | Metal Heads |
| `go-station-000090` | Femmetal Classics Radio |
| `go-station-000091` | RSTLSS |
| `go-station-000092` | Radio Bloodstream |
| `go-station-000094` | Studio Brussel Zware Gitaren |
| `go-station-000098` | metalrock.fm |
| `go-station-000101` | REGENBOGEN 2 - METAL |
| `go-station-000102` | ISKC Extreme Metal |
| `go-station-000105` | Classic 21 Metal |
| `go-station-000107` | Rock FM 105.5 |
| `go-station-000109` | 0nlineradio METAL |
| `go-station-000111` | rock.irk.ru :: main-mix |
| `go-station-000123` | ChroniX AGGRESSION |
| `go-station-000136` | HuilaGeek Radio |
| `go-station-000138` | Radio Diabolus |
| `go-station-000142` | Begoodradio.com 80s metal |
| `go-station-000143` | Gnu Radio - Metal FM |
| `go-station-000145` | The Voice Of Doom |
| `go-station-000146` | HardRadio |
| `go-station-000148` | Rock Antenne Heavy Metal |
| `go-station-000150` | RTBF Classic 21 - Metal |
| `go-station-000152` | ChroniX Radio Metalcore |
| `go-station-000155` | idobi Howl |
| `go-station-000157` | Tangra Mega Rock |
| `go-station-000163` | CORE Radio! |
| `go-station-000167` | Big R Radio - 80s Metal FM |
| `go-station-000168` | 1.FM - High Voltage Radio |
| `go-station-000173` | Hard Rock Heaven |
| `go-station-000174` | 181.FM - 80's HairBand |
| `go-station-000182` | PureRock.US - America's Pure Rock |
| `go-station-000186` | Best of Rock FM - Metal |
| `go-station-000192` | Radio Metal |
| `go-station-000194` | Virgin Radio Rockstar: Aerosmith |
| `go-station-000195` | Babe Radio |
| `go-station-000197` | Prog Palace Radio's The Armory |
| `go-station-000202` | Australian Digital Radio Network - Punk and Metal Mix (MP3) |
| `go-station-000208` | Metal FM |
| `go-station-000209` | BOLLOCKS Rock & Metal Radio |
| `go-station-000212` | Hotmix meal |
| `go-station-000213` | The Generator |
| `go-station-000216` | Pure Rock KNAC.COM |
| `go-station-000217` | Código Metal Radio |
| `go-station-000224` | Manowar Радио |
| `go-station-000225` | Metal Invasion Radio |
| `go-station-000228` | Dead2Self Radio |
| `go-station-000234` | Metalwar |
| `go-station-000236` | Overdrive Live! Station |
| `go-station-000237` | Almost Hell Radio |
| `go-station-000239` | 夜愿电台Nightwish Radio |
| `go-station-000240` | NuMetal 1.0 -JubsTones |
| `go-station-000241` | Metal Live Radio |
| `go-station-000242` | Blown |
| `go-station-000245` | SFTD RADIO |
| `go-station-000248` | Virgin Radio Rockstar: AC/DC |
| `go-station-000257` | Pantera |
| `go-station-000259` | metal rock radio |
| `go-station-000268` | Australian Digital Radio Network - Metal (MP3) |
| `go-station-000271` | Metal Radio |
| `go-station-000273` | Virgin Radio Metal |
| `go-station-000275` | Espiritu Rock |
| `go-station-000277` | 0 N - Heavy Metal on Radio |
| `go-station-000280` | Australian Digital Radio Network - 1980s Hair Metal (MP3) |
| `go-station-000281` | ROCK FM Classic Rock |
| `go-station-000283` | Tattoo metal |
| `go-station-000284` | Epic Rock Radio |
| `go-station-000286` | Prog Rock and Metal |
| `go-station-000293` | ChroniX Radio - Aggression |
| `go-station-000294` | RPR1. Heavy Metal |
| `go-station-000295` | TotalRock Radio |
| `go-station-000298` | Rock Radio Hard & Heavy SLO |
| `go-station-000301` | Monsters of Rock USSR |
| `go-station-000302` | METALSCENA netRADIO |
| `go-station-000303` | Heavy Metal History radio |
| `go-station-000310` | Heavy Music Atmospheric Radio |
| `go-station-000313` | REAL PUNK RADIO |

## État réel des 98 sources d'images SHA (deux vérifications réseau)

Parmi les 185 fiches actives qui ont un logo, il existe 98 empreintes SHA distinctes. Deux passages de GitHub Actions ont téléchargé les images et comparé les **octets réels, empreintes SHA-256, dimensions et formats** aux descripteurs signés.

- [Passe 1 — 96/98 SHA vérifiés](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/45116042897) : une discordance de descripteur et une URL indisponible.
- [Passe 2 — 94/98 SHA vérifiés](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/45116208670) : deux discordances de descripteur et deux URL indisponibles.

| Station | Anomalie observée en seconde passe |
|---|---|
| 011.fm – House of Hair (`000211`) | Image renvoyée non conforme au SHA/format/dimensions signé |
| Rock The World - Heavy Metal (`000030`) | Image renvoyée non conforme au SHA/format/dimensions signé |
| Radio ROCKS Kyiv 103.6FM HD (`000068`) | Erreur HTTP sur l'image Wikimedia |
| Megarock Radio 320k (`000289`) | Erreur de récupération de l'image du site diffuseur |

Les erreurs HTTP/réseau peuvent être **temporaires** : elles ne prouvent pas que le logo est absent sur tous les téléphones. Le cache SHA local peut également contenir une image précédemment validée. Les discordances de SHA doivent être corrigées avec une **nouvelle révision signée**, jamais en contournant le contrôle cryptographique.

[CSV — les quatre sources de logos à revoir](./4-sources-logo-a-revoir-v6.csv)

## Priorités et précautions

- **Exclusively : 5 manquants** — Deep Purple, Iron Maiden, Led Zeppelin, Led Zeppelin Only Hits, Ramones. La chaîne « Only Hits » doit conserver une identité séparée.
- **laut.fm : 14 manquants** — rechercher les visuels auprès du diffuseur, vérifier SHA-256 et dimensions avant référence au catalogue.
- **Radio Maximum : 3**, **Radio Metal On : 3**, **RauteMusik Shredded : 1** — récupérer des visuels propres à chaque programme.
- **Autres : 93** — collecter depuis sites officiels / identifiants Radio Browser, sans confondre logo de diffuseur et pochette de morceau.
- Certaines fusions proposées supprimeraient également des fiches sans logo (FluxFM MetalFM et ROCK ANTENNE Heavy Metal), mais ne doivent pas être lancées avant contrôle de continuité.

## Limites de l'audit

- Constat tiré **des 304 fiches actives de la v6 signée**, pas de 304 captures d’écran.
- Les groupes « forte confiance » reposent sur le même identifiant de programme chez le diffuseur, et pour SomaFM sur les formats officiels publiés ; pas sur une simple coïncidence de logo.
- Les groupes « à confirmer » demandent comparaison des flux ou consultation de la source officielle.
- **Aucun doublon n’a été supprimé**, **aucun logo n’a été ajouté** et **aucune APK n’a été recompilée** pendant cet audit.

## Fichiers de travail

- [CSV — toutes les 304 radios actives](./inventaire-304-radios-actives-v6.csv)
- [CSV — 119 radios sans logo](./119-radios-sans-logo-v6.csv)
