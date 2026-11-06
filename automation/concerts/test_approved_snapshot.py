"""Conservation et cohérence de la file d'approbations Concerts (hors réseau).

La validation en publication est encore exécutée dans Ondes-Catalogues :
cette vérification privée interdit surtout qu'un lot d'approbations ne perde
des fiches ou n'introduise des conflits entre artistes, lieux et dates.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit

APPROVALS = Path(__file__).resolve().parent / "approved.json"
REVIEWED_REX = {
    "go-c-20261122-toulouse-spike-and-the-gimme-gimmes":
        ("2026-11-22", ["spike-and-the-gimme-gimmes"],
         "https://www.lerextoulouse.com/fr/programmation/spike-and-the-gimme-gimmes/"),
    "go-c-20270215-toulouse-jared-james-nichols":
        ("2027-02-15", ["jared-james-nichols"],
         "https://www.lerextoulouse.com/fr/programmation/jared-james-nichols/"),
    "go-c-20270409-toulouse-komodor":
        ("2027-04-09", ["komodor", "witchorious"],
         "https://www.lerextoulouse.com/fr/programmation/komodor-et-witchorious/"),
}

class ApprovalBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document=json.loads(APPROVALS.read_text(encoding="utf-8"))
        cls.rows=cls.document["approvals"]

    def test_stranglers_official_complete_lineup_and_no_duplicate_lead_artist(self):
        identifier = "go-c-20261124-cenon-the-stranglers"
        rows = [row for row in self.rows if row["event"]["id"] == identifier]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        event = row["event"]
        self.assertEqual(row["reviewDecision"], "approved")
        self.assertEqual(row["reviewedBy"], "independent-official-verifier")
        self.assertEqual(row["reviewedAt"], "2026-11-06")
        self.assertEqual(event["title"], "The Stranglers + Brother Junior")
        self.assertEqual(event["date"], "2026-11-24")
        self.assertEqual(event["venueId"], "le-rocher-de-palmer-cenon")
        self.assertEqual(event["time"], "20:30")
        self.assertEqual(event["genres"], ["Rock"])
        self.assertEqual(event["artistIds"], ["the-stranglers", "brother-junior"])
        self.assertEqual(event["officialUrl"],
                         "https://lerocherdepalmer.fr/agenda/stranglers")
        self.assertEqual(row["newArtists"],
                         [{"id": "brother-junior", "name": "Brother Junior"}])
        self.assertNotIn("the-stranglers",
                         {a["id"] for a in row["newArtists"]})
        proof, ticket = row["officialEvidence"]
        self.assertEqual(proof["officialArtistNames"],
                         ["The Stranglers", "Brother Junior"])
        self.assertEqual(ticket["officialArtistNames"],
                         proof["officialArtistNames"])
        self.assertEqual(proof["checkedFields"],
                         ["artists", "date", "venue", "genre",
                          "startTime", "doorTime"])
        self.assertEqual(proof["concertStartTimeConfirmed"], "20:30")
        self.assertEqual(proof["doorTimeConfirmed"], "19:30")
        self.assertEqual(ticket["proofType"], "first-party-venue-ticketing")
        self.assertEqual(ticket["url"],
                         "https://billetterie.lerocherdepalmer.fr/agenda/1862-THE-STRANGLERS?session=1862")
        self.assertEqual(ticket["checkedFields"], ["artists", "date", "venue"])
        self.assertEqual(proof["checkedAt"], row["reviewedAt"])
        self.assertEqual(ticket["checkedAt"], row["reviewedAt"])

    def test_orleans_three_official_proofs_are_distinct_and_no_time_inferred(self):
        expected = {
            "go-c-20261119-orleans-razorlight":
                ("2026-11-19", ["razorlight", "rubber-legs"], "razorlight/"),
            "go-c-20270121-orleans-la-jungle":
                ("2027-01-21", ["la-jungle", "sodom-sagesse"],
                 "la-jungle-sodom-sagesse/"),
            "go-c-20270129-orleans-orpheum-black":
                ("2027-01-29", ["orpheum-black", "pledge-of-healing"],
                 "orpheum-black-le-dernier-acte/"),
        }
        by_id = {r["event"]["id"]: r for r in self.rows}
        for event_id, (date, ids, slug) in expected.items():
            with self.subTest(event=event_id):
                row = by_id[event_id]
                event = row["event"]
                self.assertEqual(event["venueId"], "l-astrolabe-orleans")
                self.assertEqual(event["date"], date)
                self.assertEqual(event["artistIds"], ids)
                self.assertIsNone(event["time"])
                self.assertEqual(row["reviewedBy"],
                                 "independent-official-verifier")
                proofs = row["officialEvidence"]
                self.assertEqual(len(proofs), 2)
                self.assertEqual(proofs[0]["url"], event["officialUrl"])
                self.assertEqual(proofs[0]["proofType"],
                                 "official-organizer-or-venue")
                self.assertTrue(event["officialUrl"].endswith(slug))
                self.assertEqual(proofs[0]["checkedAt"], "2026-11-03")
                self.assertEqual(proofs[1]["checkedAt"], "2026-11-03")
                self.assertNotEqual(proofs[0]["url"], proofs[1]["url"])
                if event_id=="go-c-20261119-orleans-razorlight":
                    self.assertEqual(proofs[1]["url"],
                                     "https://www.lastrolabe.org/agenda/")
                    self.assertEqual(event["title"], "Razorlight + Rubber Legs")
                if event_id=="go-c-20270129-orleans-orpheum-black":
                    self.assertIn("Pledge of Healing", event["title"])
                    self.assertEqual(event["organizer"], "SLAPTRACK")
                self.assertNotIn("startTime", proofs[0]["checkedFields"])
                self.assertNotIn("startTime", proofs[1]["checkedFields"])

    def test_three_rouen_concerts_are_signed_without_unjustified_start(self):
        expected={
            "go-c-20261117-rouen-elktrk-skin": (
                "2026-11-17", ["elktrk-skin", "yu-band", "kaask"],
                "https://le106.com/agenda/elktrk-skin-yu-kaask"),
            "go-c-20270128-rouen-powersolo": (
                "2027-01-28", ["powersolo", "weird-omen", "dj-tony-garagist"],
                "https://le106.com/agenda/power-solo-weird-omen-dj-tony-garagist"),
            "go-c-20270313-rouen-dynamite-shakers": (
                "2027-03-13", ["dynamite-shakers"],
                "https://le106.com/agenda/dynamite-shakers"),
        }
        by_id={r["event"]["id"]:r for r in self.rows}
        for eid,(day,artists,url) in expected.items():
            with self.subTest(eid=eid):
                row=by_id[eid]
                event=row["event"]
                self.assertEqual(event["venueId"],"le-106-rouen")
                self.assertEqual(event["date"],day)
                self.assertEqual(event["artistIds"],artists)
                self.assertEqual(event["officialUrl"],url)
                self.assertEqual(event["status"],"confirmed")
                self.assertIsNone(event["time"])
                self.assertEqual(row["reviewedBy"],"independent-official-verifier")
                evidence=row["officialEvidence"]
                self.assertEqual(len(evidence),2)
                self.assertEqual(evidence[0]["proofType"],"official-organizer-or-venue")
                self.assertEqual(evidence[0]["url"],url)
                self.assertTrue({"artists","date","venue","genre"}.issubset(
                    set(evidence[0]["checkedFields"])))
                self.assertTrue({"artists","date","venue"}.issubset(
                    set(evidence[1]["checkedFields"])))
                self.assertNotEqual(evidence[0]["url"],evidence[1]["url"])
                self.assertNotIn("startTime",evidence[0]["checkedFields"])
                self.assertNotIn("startTime",evidence[1]["checkedFields"])
        # No event may inherit a festival date solely from the Cosmic Trip
        # festival name. It is explicitly the one-night touring show in Rouen.
        self.assertNotIn("Festival",by_id[
            "go-c-20270128-rouen-powersolo"]["event"]["title"])

    def test_schema_and_unique_identifiers(self):
        self.assertEqual(self.document["schema"],"grossesondes.concert.approvals.v1")
        self.assertLessEqual(len(self.rows), 400)
        ids=[x["event"]["id"] for x in self.rows]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertGreaterEqual(len(ids),18)

    def test_every_approval_has_first_party_evidence_and_no_fake_time(self):
        for row in self.rows:
            e=row["event"]
            with self.subTest(id=e["id"]):
                self.assertEqual(row["reviewDecision"],"approved")
                self.assertRegex(e["id"],r"^go-c-[a-z0-9-]+$")
                self.assertTrue(e["title"])
                self.assertEqual(e["status"],"confirmed")
                self.assertIn(e["sourceType"],("salle","organisateur"))
                dt.date.fromisoformat(e["date"])
                self.assertTrue(e["artistIds"])
                self.assertEqual(len(e["artistIds"]),len(set(e["artistIds"])))
                self.assertTrue(e["genres"])
                self.assertEqual(urlsplit(e["officialUrl"]).scheme,"https")
                if e["id"]=="go-c-20261114-paris-the-vintage-caravan":
                    # Glazart only names the headline + unnamed guest; the
                    # Garmonbozia ticket documents Damantra and date.
                    proofs=row["officialEvidence"]
                    self.assertEqual(len(proofs),2)
                    self.assertEqual(proofs[0]["url"],e["officialUrl"])
                    self.assertTrue({"leadArtist","date","venue","genre"}.issubset(
                        set(proofs[0]["checkedFields"])))
                    self.assertNotIn("artists",proofs[0]["checkedFields"])
                    self.assertEqual(proofs[1]["proofType"],"organizer-ticketing-detail")
                    self.assertTrue({"artists","date","venue","genre"}.issubset(
                        set(proofs[1]["checkedFields"])))
                elif e["id"]=="go-c-20261113-strasbourg-local-heroes":
                    # Ticket: lineup/date/venue; first-party calendar: genre/date/venue.
                    # Neither source alone proves fields it does not contain.
                    proofs=row.get("officialEvidence",[])
                    self.assertEqual(len(proofs),2)
                    self.assertTrue(any(p.get("url")==e["officialUrl"]
                        and p.get("proofType")=="official-organizer-or-venue"
                        and {"artists","date","venue"}.issubset(
                            set(p.get("checkedFields") or [])) for p in proofs))
                    self.assertTrue(any(
                        p.get("proofType")=="first-party-venue-calendar"
                        and p.get("url")=="https://www.lamaisonbleue-stbg.com/agenda/"
                        and {"date","venue","genre"}.issubset(
                            set(p.get("checkedFields") or [])) for p in proofs))
                elif e["id"] in (
                    "go-c-20261205-secret-place-cracked-heads",
                    "go-c-20261206-secret-place-the-spitters"):
                    # Organizer Wix pages prove the exact official date,
                    # venue and named artists, NOT a musical start time and
                    # NOT the band's genre. External editorial genre context
                    # is kept as separately attributed evidence.
                    proofs=row["officialEvidence"]
                    self.assertEqual(len(proofs),2)
                    self.assertEqual(proofs[0]["url"],e["officialUrl"])
                    self.assertEqual(proofs[0]["proofType"],"official-organizer-or-venue")
                    self.assertTrue({"artists","date","venue"}.issubset(
                        set(proofs[0]["checkedFields"])))
                    self.assertNotIn("genre",proofs[0]["checkedFields"])
                    self.assertNotIn("startTime",proofs[0]["checkedFields"])
                    self.assertEqual(proofs[1]["proofType"],"editorial-genre-context")
                    self.assertTrue({"artists","date","venue","genre"}.issubset(
                        set(proofs[1]["checkedFields"])))
                    self.assertIsNone(e["time"])
                elif e["id"]=="go-c-20261121-paris-horskh":
                    # The individual Horskh page names the support band and
                    # genre, but omits the YEAR. Only the dated official
                    # November 2026 calendar supplies the full date.
                    proofs=row["officialEvidence"]
                    self.assertEqual(len(proofs),2)
                    self.assertEqual(proofs[0]["url"],e["officialUrl"])
                    self.assertEqual(proofs[0]["proofType"],"official-organizer-or-venue")
                    self.assertTrue({"artists","venue","genre"}.issubset(
                        set(proofs[0]["checkedFields"])))
                    self.assertNotIn("date",proofs[0]["checkedFields"])
                    self.assertEqual(proofs[1]["url"],
                                     "https://www.lamaroquinerie.fr/fr/agenda/")
                    self.assertEqual(proofs[1]["proofType"],
                                     "first-party-venue-calendar")
                    self.assertTrue({"artists","date","venue"}.issubset(
                        set(proofs[1]["checkedFields"])))
                elif e["id"]=="go-c-20270210-lorient-revnoir-ice-sealed-eyes":
                    # Hydrophone SPIP gives day+month but omits YEAR entirely.
                    # A distinct authorized ticket distributor proves 2027.
                    proofs=row["officialEvidence"]
                    self.assertEqual(len(proofs),2)
                    self.assertEqual(proofs[0]["url"],e["officialUrl"])
                    self.assertEqual(proofs[0]["proofType"],
                                     "official-organizer-or-venue")
                    self.assertTrue({"artists","day","month","venue",
                                     "genre","startTime"}.issubset(
                                         set(proofs[0]["checkedFields"])))
                    self.assertNotIn("date",proofs[0]["checkedFields"])
                    self.assertEqual(proofs[1]["proofType"],
                                     "authorized-ticket-distributor-full-date")
                    self.assertTrue({"artists","date","year","venue",
                                     "startTime"}.issubset(
                                         set(proofs[1]["checkedFields"])))
                    self.assertEqual(proofs[1]["dateConfirmed"],e["date"])
                    self.assertEqual(proofs[1]["startTimeConfirmed"],e["time"])
                elif e["id"] in (
                    "go-c-20261119-orleans-razorlight",
                    "go-c-20270129-orleans-orpheum-black",
                ):
                    # The venue's single-event page documents the headliner,
                    # date, room and genre, while a distinct first-party
                    # calendar or organizer ticket establishes the support act.
                    # Never claim the individual page listed both performers.
                    proofs=row["officialEvidence"]
                    self.assertEqual(len(proofs), 2)
                    self.assertEqual(proofs[0]["url"], e["officialUrl"])
                    self.assertEqual(proofs[0]["proofType"], "official-organizer-or-venue")
                    self.assertTrue({"leadArtist","date","venue","genre"}.issubset(
                        set(proofs[0].get("checkedFields") or [])))
                    self.assertNotIn("artists", proofs[0]["checkedFields"])
                    self.assertTrue({"artists","date","venue"}.issubset(
                        set(proofs[1].get("checkedFields") or [])))
                    self.assertIn(proofs[1]["proofType"], (
                        "first-party-venue-calendar",
                        "independent-organizer-confirmation"))
                    self.assertNotEqual(proofs[0]["url"], proofs[1]["url"])
                    self.assertNotIn("startTime", proofs[1]["checkedFields"])
                elif e["venueId"] == "le-tetris-le-havre":
                    # Le Tetris affiche jour/mois et artistes, mais PAS
                    # l'année. Une seconde source nominative à date complète
                    # doit obligatoirement établir le millésime séparément.
                    proofs = row["officialEvidence"]
                    self.assertEqual(len(proofs), 2)
                    official, external = proofs
                    self.assertEqual(official["url"], e["officialUrl"])
                    self.assertEqual(official["proofType"], "official-organizer-or-venue")
                    self.assertTrue({"artists", "venue", "genre", "dayMonth"}.issubset(
                        set(official.get("checkedFields") or [])))
                    self.assertNotIn("date", official["checkedFields"])
                    self.assertNotIn("fullDate", official["checkedFields"])
                    self.assertIn(external["proofType"], (
                        "event-partner-full-date", "official-tourism-full-date",
                        "independent-concert-calendar-full-date",
                        "official-artist-tour-full-date"))
                    self.assertTrue({"artists", "venue", "fullDate"}.issubset(
                        set(external.get("checkedFields") or [])))
                    self.assertNotEqual(official["url"], external["url"])
                    self.assertIsNone(e["time"])
                elif e["id"] in {
                    "go-c-20261210-rouen-the-sheepdogs-steve-hill",
                    "go-c-20270121-rouen-skip-the-use-mdns",
                    "go-c-20270126-rouen-editors-big-sleep",
                    "go-c-20270311-rouen-steve-n-seagulls",
                    "go-c-20270413-rouen-peter-hook-and-the-light",
                    "go-c-20270515-rouen-tagada-jones",
                    "go-c-20261212-rouen-maustetytot-francis",
                }:
                    # Le 106: artist/genre in the first-party event detail,
                    # full date independently proven by the exact calendar page.
                    # Never attribute historical album years or displayed
                    # doors to the concert start time.
                    proofs=row["officialEvidence"]
                    self.assertEqual(len(proofs),2)
                    first,cal=proofs
                    self.assertEqual(first["url"],e["officialUrl"])
                    self.assertEqual(first["proofType"],"official-organizer-or-venue")
                    self.assertTrue({"artists","venue","genre"}.issubset(
                        set(first["checkedFields"])))
                    self.assertNotIn("date",first["checkedFields"])
                    self.assertNotIn("startTime",first["checkedFields"])
                    self.assertEqual(cal["url"],"https://le106.com/agenda?page="+(
                        "2" if e["id"] in {
                            "go-c-20270311-rouen-steve-n-seagulls",
                            "go-c-20270413-rouen-peter-hook-and-the-light",
                            "go-c-20270515-rouen-tagada-jones"
                        } else "1"))
                    self.assertEqual(cal["proofType"],"first-party-venue-calendar")
                    self.assertTrue({"artists","date","venue"}.issubset(
                        set(cal["checkedFields"])))
                    self.assertNotIn("startTime",cal["checkedFields"])
                    self.assertIsNone(e["time"])
                elif e["id"] in (
                        "go-c-20261106-limoges-7weeks",
                        "go-c-20261127-limoges-gwendoline"):
                    # La fiche municipale détaille le jour et le mois,
                    # le calendrier municipal prouve séparément l'année 2026.
                    # Ne jamais prétendre que la fiche seule donne cette année.
                    first, cal = row["officialEvidence"]
                    self.assertEqual(first["url"], e["officialUrl"])
                    self.assertEqual(first["proofType"], "official-organizer-or-venue")
                    self.assertTrue({"artists", "dayMonth", "venue", "genre"}.issubset(
                        set(first["checkedFields"])))
                    self.assertNotIn("date", first["checkedFields"])
                    self.assertEqual(
                        cal["url"], "https://centresculturels.limoges.fr/agenda?keys=hiero")
                    self.assertEqual(cal["proofType"], "first-party-venue-calendar")
                    self.assertTrue({"artists", "date", "venue"}.issubset(
                        set(cal["checkedFields"])))
                    self.assertIsNone(e["time"])
                elif e["id"] in (
                        "go-c-20261211-colmar-wake-the-dead",
                        "go-c-20270130-colmar-easy-cure"):
                    # Both official Grillen detail pages name the bill and
                    # day/month; only the independent Coze event listing
                    # explicitly supplies the 2026/2027 year.
                    official, external = row["officialEvidence"]
                    self.assertEqual(len(row["officialEvidence"]), 2)
                    self.assertEqual(official["url"], e["officialUrl"])
                    self.assertEqual(official["proofType"],
                                     "official-organizer-or-venue")
                    self.assertEqual(set(official["checkedFields"]),
                                     {"artists", "dayMonth", "venue", "genre"})
                    self.assertNotIn("date", official["checkedFields"])
                    self.assertEqual(external["proofType"],
                                     "independent-event-listing")
                    self.assertEqual(set(external["checkedFields"]),
                                     ({"artists", "date", "venue", "genre"}
                                      if e["id"].endswith("easy-cure")
                                      else {"artists", "date", "venue"}))
                    self.assertNotEqual(official["url"], external["url"])
                    self.assertIsNone(e["time"])
                elif e["id"] == "go-c-20270211-dijon-skip-the-use":
                    # Live Nation alone proves the complete 2027 date; the
                    # venue's own programme confirms Rock but not the year.
                    # Do not weaken the default all-fields-on-primary rule.
                    self.assertEqual(e["title"], "Skip The Use")
                    self.assertEqual(e["date"], "2027-02-11")
                    self.assertEqual(e["venueId"], "la-vapeur-dijon")
                    self.assertEqual(e["artistIds"], ["skip-the-use"])
                    self.assertEqual(e["genres"], ["Rock"])
                    self.assertIsNone(e["time"])
                    self.assertEqual(len(row["officialEvidence"]), 2)
                    first, calendar = row["officialEvidence"]
                    self.assertEqual(
                        first["url"],
                        "https://www.livenation.fr/event/skip-the-use-love-and-anxiety-dijon-tickets-edp1674591")
                    self.assertEqual(first["proofType"], "official-organizer-or-venue")
                    self.assertEqual(first["checkedFields"], ["artists", "date", "venue"])
                    self.assertEqual(
                        calendar["url"], "https://www.lavapeur.com/programme/")
                    self.assertEqual(calendar["proofType"], "first-party-venue-calendar")
                    self.assertEqual(
                        calendar["checkedFields"],
                        ["artists", "venue", "genre", "dayMonth"])
                    self.assertTrue(all(p["checkedAt"] == "2026-11-04"
                                        for p in (first, calendar)))
                    self.assertNotEqual(first["url"], calendar["url"])
                    self.assertNotIn("concertStartTime", first["checkedFields"])
                    self.assertNotIn("date", calendar["checkedFields"])
                elif e["id"]=="go-c-20270122-paris-7weeks":
                    # La tournée officielle française prouve date/artiste/lieu,
                    # Eventim prouve une seconde fois la date ; le guest est anonyme.
                    first,ticket=row["officialEvidence"]
                    self.assertEqual((first["url"],first["proofType"]),
                        (e["officialUrl"],"official-artist-tour-calendar"))
                    self.assertEqual(set(first["checkedFields"]),
                        {"artists","date","venue"})
                    self.assertEqual(ticket["proofType"],
                        "authorized-ticket-distributor-full-date")
                    self.assertEqual(set(ticket["checkedFields"]),
                        {"artists","date","venue"})
                    self.assertEqual(e["artistIds"],["7weeks"])
                    self.assertEqual(e["genres"],["Heavy Rock"])
                    self.assertIsNone(e["time"])
                elif e["id"] == "go-c-20261118-rennes-marillion-lazuli":
                    # La fiche du MeM n'annonce que Marillion. Lazuli est
                    # validé indépendamment par ses propres dates et le groupe.
                    proofs = row["officialEvidence"]
                    self.assertEqual(len(proofs),4)
                    first, support, band, organizer = proofs
                    self.assertEqual(first["url"],e["officialUrl"])
                    self.assertEqual(first["proofType"],"official-organizer-or-venue")
                    self.assertEqual(first["checkedFields"],
                                     ["leadArtist","date","venue","genre"])
                    self.assertEqual(first["confirmedArtists"],["Marillion"])
                    self.assertEqual(support["url"],"https://lazuli-music.com/tour/")
                    self.assertEqual(support["confirmedArtists"],["Marillion","Lazuli"])
                    self.assertEqual(band["url"],"https://www.marillion.com/tour/")
                    self.assertEqual(band["confirmedArtists"],["Marillion","Lazuli"])
                    self.assertEqual(organizer["url"],"https://www.aegpresents.fr/event/marillion/")
                    self.assertEqual(e["artistIds"],["marillion","lazuli"])
                    self.assertEqual(e["date"],"2026-11-18")
                    self.assertIsNone(e["time"])
                    self.assertTrue(all(p["checkedAt"]=="2026-11-05" for p in proofs))
                    self.assertFalse(any("concertStartTime" in p["checkedFields"]
                                         for p in proofs))
                elif e["id"] == "go-c-20261208-nantes-fff-howlin-jaws":
                    # Stereolux n'indique PAS le nom de la première partie.
                    # Seule l'agence de Howlin' Jaws établit son identité.
                    first, second = row["officialEvidence"]
                    self.assertEqual(first["url"], e["officialUrl"])
                    self.assertEqual(first["proofType"], "official-organizer-or-venue")
                    self.assertEqual(first["checkedFields"],
                                     ["leadArtist","date","venue","supportUnspecified"])
                    self.assertEqual(first["confirmedArtists"], ["FFF"])
                    self.assertEqual(second["url"],
                                     "https://radical-production.fr/artistes/howlin-jaws/")
                    self.assertEqual(second["proofType"],
                                     "independent-official-support-agent")
                    self.assertEqual(second["confirmedArtists"],
                                     ["FFF","Howlin' Jaws"])
                    self.assertEqual(e["artistIds"], ["fff","howlin-jaws"])
                    self.assertIsNone(e["time"])
                else:
                    self.assertTrue(any(p.get("url")==e["officialUrl"]
                        and p.get("proofType")=="official-organizer-or-venue"
                        and set(("artists","date","venue","genre")).issubset(
                            p.get("checkedFields") or [])
                        for p in row.get("officialEvidence", [])))
                self.assertTrue(e["time"] is None or
                    re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",e["time"]))

    def test_no_same_venue_date_and_artist_twice(self):
        occupied=set()
        for row in self.rows:
            e=row["event"]
            for artist_id in e["artistIds"]:
                key=(e["date"],e["venueId"],artist_id)
                self.assertNotIn(key,occupied)
                occupied.add(key)

    def test_three_rex_fiches_independent_review_only(self):
        byid={row["event"]["id"]:row for row in self.rows}
        for ident,(date,names,url) in REVIEWED_REX.items():
            with self.subTest(id=ident):
                self.assertIn(ident,byid)
                row=byid[ident]
                e=row["event"]
                self.assertEqual(e["date"],date)
                self.assertEqual(e["venueId"],"le-rex-toulouse")
                self.assertEqual(e["artistIds"],names)
                self.assertEqual(e["officialUrl"],url)
                self.assertIsNone(e["time"])
                self.assertEqual(row["reviewedBy"],"independent-official-verifier")
                self.assertEqual(
                    {a["id"] for a in row["newArtists"]},set(names))
                self.assertFalse(any("guest" in x.casefold() for x in
                                     [e["title"],*e["genres"]]))


    def test_secret_place_december_signed_punk_details_without_inferred_start(self):
        expected={
            "go-c-20261205-secret-place-cracked-heads":
              ("2026-12-05","The Cracked Heads + The Psychotic Unicorns + Noble Rot",
               ["the-cracked-heads","the-psychotic-unicorns","noble-rot"],
               ["The Cracked Heads","The Psychotic Unicorns","Noble Rot"],
               ["Garage Punk"],
               "https://www.toutafond.com/event-details/the-cracked-heads-the-psychotic-unicorns-noble-rot",
               "https://montpellier.concerts-metal.com/"),
            "go-c-20261206-secret-place-the-spitters":
              ("2026-12-06","The Spitters + Panic Lights",
               ["the-spitters","panic-lights"],
               ["The Spitters","Panic Lights"],
               ["Punk Rock"],
               "https://www.toutafond.com/event-details/la-taf-boomerang-presentent-the-spitters-panic-lights",
               "https://www.lagazettedenimes.fr/agenda/musiques-2026-12-06-rock-et-punk-secret-place-saint-jean-de-vedas/")
        }
        rows={r["event"]["id"]:r for r in self.rows}
        for ident,(date,title,ids,names,genres,first,second) in expected.items():
            with self.subTest(event=ident):
                r=rows[ident];e=r["event"]
                self.assertEqual((e["title"],e["date"],e["artistIds"],
                                  e["genres"],e["officialUrl"],e["time"],
                                  e["venueId"]),
                    (title,date,ids,genres,first,None,
                     "secret-place-saint-jean-de-vedas"))
                self.assertEqual([a["id"] for a in r["newArtists"]],ids)
                self.assertEqual([a["name"] for a in r["newArtists"]],names)
                self.assertEqual(len(r["officialEvidence"]),2)
                self.assertEqual((r["officialEvidence"][0]["url"],
                                  r["officialEvidence"][1]["url"]),
                                 (first,second))
                self.assertEqual(r["reviewDecision"],"approved")
                self.assertEqual(r["reviewedBy"],"independent-official-verifier")
                self.assertEqual(r["reviewedAt"],"2026-11-02")
                self.assertTrue(all(p["checkedAt"]=="2026-11-02"
                    for p in r["officialEvidence"]))
                self.assertIsNone(e["time"])
        self.assertFalse(any("veenus" in x["event"]["id"] or
                             "flying-bananas" in x["event"]["id"]
                             for x in self.rows))

    def test_verified_pilot_venues_documented(self):
        items=self.document.get("venueApprovals",[])
        self.assertTrue({a["venue"]["id"] for a in items}.issuperset(
            {"jokers-pub-angers","le-brin-de-zinc-barberaz",
              "backstage-by-the-mill-paris","rock-n-eat-lyon",
              "la-maison-bleue-strasbourg","glazart-paris","le-trabendo-paris",
              "la-maroquinerie-paris","la-boule-noire-paris",
              "le-forum-vaureal","la-cave-aux-poetes-roubaix",
              "la-carene-brest","atabal-biarritz","hydrophone-lorient",
              "le-chatodo-blois","le-temps-machine-joue-les-tours",
              "le-tetris-le-havre","bonjour-minuit-saint-brieuc","le-jardin-moderne-rennes"}))
        self.assertGreaterEqual(len(items), 19)
        for row in items:
            v=row["venue"]
            with self.subTest(venue=v["id"]):
                self.assertEqual(row["reviewDecision"],"approved")
                self.assertEqual(row["reviewedBy"],"independent-official-verifier")
                self.assertTrue(v["postalCode"].isdigit())
                self.assertIsInstance(v["latitude"],float)
                self.assertIsInstance(v["longitude"],float)
                self.assertLessEqual(len(v["address"]),120)
                types={p["proofType"] for p in row["officialEvidence"]}
                if v["id"]=="le-mem-rennes":
                    self.assertEqual(types,{
                        "official-venue-address",
                        "first-party-venue-map",
                        "independent-geotagged-photo-2026"})
                else:
                    self.assertEqual(types,{"official-venue-address",
                        "independent-named-venue-geolocation" if v["id"] in ("le-sew-morlaix","la-manufacture-saint-quentin","l-orange-bleue-vitry-le-francois","la-clef-saint-germain-en-laye") else
                        "openstreetmap-venue-way" if v["id"]=="espace-bel-air-saint-aubin-du-cormier" else
                        "independent-venue-coordinate-listing" if v["id"]=="l-echonova-saint-ave" else
                        "government-accessibility-location" if v["id"]=="bonjour-minuit-saint-brieuc" else
                        "official-venue-gps" if v["id"]=="hydrophone-lorient" else
                        "official-tourism-geo" if v["id"]=="atabal-biarritz" else
                        "independent-venue-gps" if v["id"]=="le-temps-machine-joue-les-tours" else
                        "independent-tourism-event-gps" if v["id"]=="le-bateau-ivre-tours" else
                        "independent-tourism-gps" if v["id"] in ("le-tetris-le-havre","cepac-silo-marseille") else
                        "openstreetmap-venue-way" if v["id"] in ("glazart-paris","le-trabendo-paris","la-carene-brest","le-chatodo-blois","le-jardin-moderne-rennes","casino-de-paris","radiant-bellevue-caluire","6mic-aix-en-provence","salle-cap-caval-penmarch","marche-gare-lyon")
                        else "independent-institutional-venue-gps" if v["id"]=="stereolux-nantes" else
                        "first-party-venue-map" if v["id"]=="le-mem-rennes" else
                        "openstreetmap-venue-node"})
                    if v["id"] in ("casino-de-paris","radiant-bellevue-caluire","cepac-silo-marseille"):
                        verified = {
                            "casino-de-paris": (
                                "https://www.casinodeparis.fr/fr/infos-pratiques",
                                "https://mapcarta.com/fr/26253924",
                                (48.87845, 2.33051)),
                            "radiant-bellevue-caluire": (
                                "https://radiant-bellevue.fr/contact-acces/",
                                "https://mapcarta.com/fr/W299047133",
                                (45.79795, 4.84301)),
                            "cepac-silo-marseille": (
                                "https://www.cepacsilo-marseille.fr/infos-pratiques/",
                                "https://www.cirkwi.com/en/point-interet/4687013-le-silo",
                                (43.310475, 5.366558)),
                        }
                        official_url, gps_url, coordinate = verified[v["id"]]
                        self.assertEqual(row["officialEvidence"][0]["url"], official_url)
                        self.assertEqual(row["officialEvidence"][1]["url"], gps_url)
                        self.assertEqual(v["geoSource"], gps_url)
                        self.assertEqual((v["latitude"],v["longitude"]), coordinate)
                        self.assertIn("indicatif",v["geoPrecision"])
                if v["id"]=="le-mem-rennes":
                    expected_map = "https://www.google.com/maps/place/Le+MeM+-+Magic+Mirror/"
                    self.assertTrue(v["geoSource"].startswith(expected_map))
                    self.assertEqual((v["latitude"],v["longitude"]),(48.1032992,-1.7184605))
                    self.assertEqual(
                        [x["proofType"] for x in row["officialEvidence"]],
                        ["official-venue-address","first-party-venue-map","independent-geotagged-photo-2026"])
                    self.assertEqual(row["officialEvidence"][2]["photoDate"],"2026-10-18")
                    self.assertIn("indicatif",v["geoPrecision"])
                    continue
                if v["id"] == "stereolux-nantes":
                    self.assertEqual(v["geoSource"],
                        "https://www.univ-nantes.fr/plans-des-campus/stereolux")
                    self.assertEqual((v["latitude"], v["longitude"]),
                                     (47.205119, -1.563498))
                    self.assertEqual(row["officialEvidence"][1]["proofType"],
                                     "independent-institutional-venue-gps")
                    continue
                if v["id"] in ("la-manufacture-saint-quentin",
                                "l-orange-bleue-vitry-le-francois"):
                    exact = {
                        "la-manufacture-saint-quentin": (
                            "https://tofromfrance.com/lieu/le-concert-des-deux-pianos-a-la-manufacture",
                            (49.85444,3.27029)),
                        "l-orange-bleue-vitry-le-francois": (
                            "https://musitree.fr/concerts/salles/bords-2-scenes-lorange-bleue-vitry-le-francois/",
                            (48.72668,4.57955)),
                    }
                    geo_url,point=exact[v["id"]]
                    self.assertEqual(v["geoSource"],geo_url)
                    self.assertEqual((v["latitude"],v["longitude"]),point)
                    self.assertEqual(row["officialEvidence"][1]["url"],geo_url)
                    self.assertIn("indicatif",v["geoPrecision"])
                    continue
                if v["id"] == "la-clef-saint-germain-en-laye":
                    self.assertEqual(v["geoSource"],
                        "https://musitree.fr/concerts/salles/la-clef-saint-germain-en-laye-saint-germain-en-laye/")
                    self.assertEqual((v["latitude"],v["longitude"]),(48.89409,2.08842))
                    self.assertIn("indicatif",v["geoPrecision"])
                    continue
                if v["id"] == "espace-bel-air-saint-aubin-du-cormier":
                    self.assertEqual(v["geoSource"],
                        "https://mapcarta.com/fr/W117002146")
                    self.assertEqual((v["latitude"],v["longitude"]),(48.25787,-1.38968))
                    self.assertIn("indicatif",v["geoPrecision"])
                    continue
                if v["id"] == "le-sew-morlaix":
                    self.assertEqual(v["geoSource"],
                        "https://musitree.fr/concerts/salles/sew-la-manu-morlaix/")
                    self.assertEqual((v["latitude"],v["longitude"]),(48.58309,-3.83484))
                    self.assertIn("indicatif",v["geoPrecision"])
                    continue
                self.assertTrue(v["geoSource"].startswith(("https://mapcarta.com/",
                    "https://www.openstreetmap.org/api/0.6/node/",
                    "https://www.openstreetmap.org/api/0.6/way/",
                    "https://www.tourisme64.com/",
                    "https://www.hydrophone.fr/",
                    "https://www.aleou.fr/",
                    "https://www.cirkwi.com/",
                    "https://acceslibre.beta.gouv.fr/",
                    "https://www.fandefest.com/",
                    "https://www.loisirs-divertissements.com/")))

    def test_cave_poetes_exact_venue_point_20261108_and_three_punk_bands(self):
        v=next(x for x in self.document["venueApprovals"]
               if x["venue"]["id"]=="la-cave-aux-poetes-roubaix")
        geo=v["venue"]
        self.assertEqual(geo["name"],"La Cave aux Poètes")
        self.assertEqual((geo["city"],geo["address"]),
                         ("Roubaix","16 rue du Grand Chemin"))
        self.assertEqual((geo["latitude"],geo["longitude"]),(50.6921711,3.1692704))
        self.assertEqual(geo["geoSource"],
                         "https://www.openstreetmap.org/api/0.6/node/5902484873")
        self.assertEqual(v["officialEvidence"][0]["url"],
                         "https://caveauxpoetes.com/pratique/")
        self.assertEqual(v["officialEvidence"][1]["proofType"],
                         "openstreetmap-venue-node")
        a=next(x for x in self.rows if x["event"]["id"]==
               "go-c-20261108-roubaix-babe-haven-latter-muddle")
        e=a["event"]
        self.assertEqual((e["title"],e["date"],e["time"]),
            ("Babe Haven + Latter + Muddle","2026-11-08","18:30"))
        self.assertEqual(e["venueId"],"la-cave-aux-poetes-roubaix")
        self.assertEqual(e["artistIds"],["babe-haven","latter","muddle"])
        self.assertEqual(e["genres"],["Punk","Nu Metal"])
        self.assertEqual(a["newArtists"],[
            {"id":"babe-haven","name":"Babe Haven"},
            {"id":"latter","name":"Latter"},
            {"id":"muddle","name":"Muddle"}])
        self.assertEqual(len(a["officialEvidence"]),2)
        first,second=a["officialEvidence"]
        self.assertEqual(first["url"],
            "https://caveauxpoetes.com/evenement/babe-haven-latter-muddle/")
        self.assertEqual(first["proofType"],"official-organizer-or-venue")
        self.assertTrue({"artists","date","venue","genre","startTime"}.issubset(
            set(first["checkedFields"])))
        self.assertIn("OUVERTURE DES PORTES : 18H / CONCERTS : 18H30",
                      first["notes"])
        self.assertEqual(second["proofType"],"organizer-submitted-calendar")
        self.assertEqual(second["url"],
            "https://openagenda.com/fr/la-cave-aux-poetes/events/32006543_babe-haven-latter-muddle")
        self.assertTrue({"artists","date","venue","startTime"}.issubset(
            set(second["checkedFields"])))
        self.assertIn("Même organisateur",second["notes"])
        self.assertEqual(a["reviewedBy"],"independent-official-verifier")
        self.assertEqual(a["reviewedAt"],"2026-11-02")

    def test_forum_sortilege_and_motocultor_cross_proofs_and_no_submask(self):
        records={r["event"]["id"]:r for r in self.rows}
        expected={
            "go-c-20270115-vaureal-motocultor-tour": {
                "date":"2027-01-15","time":"19:00","genre":["Metal"],
                "title":"Rhapsody of Fire + Serious Black + Submasq + Aeon Gods + Rock Out",
                "artists":["rhapsody-of-fire","serious-black","submasq",
                           "aeon-gods","rock-out"],
                "official":"https://leforum.cergypontoise.fr/agenda/motocultor-across-europe-tour-2027",
                "secondary":"https://www.motocultor-festival.com/motocultor-across-europe-tour-2027/",
                "proofType":"official-organizer-tour","new":[]},
            "go-c-20270423-vaureal-sortilege": {
                "date":"2027-04-23","time":"20:30","genre":["Heavy Metal"],
                "title":"Sortilège","artists":["sortilege"],
                "official":"https://leforum.cergypontoise.fr/agenda/sortilege",
                "secondary":"https://sortilege.website/concerts/",
                "proofType":"official-artist-tour",
                "new":[{"id":"sortilege","name":"Sortilège"}]},
        }
        for key,spec in expected.items():
            with self.subTest(key=key):
                r=records[key]; e=r["event"]
                self.assertEqual(e["venueId"],"le-forum-vaureal")
                self.assertEqual((e["title"],e["date"],e["time"],
                                  e["genres"],e["artistIds"],e["officialUrl"]),
                    (spec["title"],spec["date"],spec["time"],
                     spec["genre"],spec["artists"],spec["official"]))
                self.assertEqual(r["newArtists"],spec["new"])
                self.assertEqual(r["reviewDecision"],"approved")
                self.assertEqual(r["reviewedBy"],"independent-official-verifier")
                self.assertEqual(r["reviewedAt"],"2026-11-02")
                self.assertEqual(len(r["officialEvidence"]),2)
                primary,second=r["officialEvidence"]
                self.assertEqual((primary["url"],primary["proofType"]),
                                 (spec["official"],"official-organizer-or-venue"))
                self.assertTrue({"artists","date","venue","genre","startTime"}.issubset(
                    set(primary["checkedFields"])))
                self.assertEqual((second["url"],second["proofType"]),
                                 (spec["secondary"],spec["proofType"]))
                self.assertTrue({"artists","date","venue"}.issubset(
                    set(second["checkedFields"])))
                self.assertEqual(primary["checkedAt"],"2026-11-02")
                self.assertEqual(second["checkedAt"],"2026-11-02")
        self.assertNotIn("submask",
                         [n for r in self.rows
                          for n in r["event"]["artistIds"]])
        self.assertTrue(all(
            len(records[key]["officialEvidence"])==2 for key in expected))

    def test_forum_five_named_concerts_and_precise_osm_node_proof(self):
        expected={
            "go-c-20261106-vaureal-senser-psykup":
                ("2026-11-06","Senser + Psykup",["senser","psykup"],
                 ["senser"],["Rap Rock"],"20:00","senser"),
            "go-c-20261107-vaureal-wolves-throne-room":
                ("2026-11-07","Wolves in the Throne Room + Worm + Final Dose",
                 ["wolves-in-the-throne-room","worm","final-dose"],
                 ["wolves-in-the-throne-room","worm","final-dose"],
                 ["Black Metal"],None,"wolves-throne-room"),
            "go-c-20261112-vaureal-mass-hysteria":
                ("2026-11-12","Mass Hysteria",["mass-hysteria"],[],
                 ["Metal"],"20:30","mass-hysteria"),
            "go-c-20270317-vaureal-michael-schenker-group":
                ("2027-03-17","Michael Schenker Group",
                 ["michael-schenker-group"],[],
                 ["Hard Rock","Metal"],"19:30","michael-schenker-group"),
            "go-c-20270522-vaureal-hard-rock-party":
                ("2027-05-22","Harsh + Furies + Charcoal",
                 ["harsh","furies","charcoal"],["harsh","furies","charcoal"],
                 ["Hard Rock"],"20:00","hard-rock-party"),
        }
        byid={x["event"]["id"]:x for x in self.rows}
        for ident,(date,title,ids,added,genres,start,slug) in expected.items():
            with self.subTest(ident=ident):
                a=byid[ident]; e=a["event"]
                url="https://leforum.cergypontoise.fr/agenda/"+slug
                self.assertEqual((e["title"],e["date"],e["artistIds"],
                                  e["genres"],e["time"],e["officialUrl"],
                                  e["venueId"]),
                     (title,date,ids,genres,start,url,"le-forum-vaureal"))
                self.assertEqual(a["reviewDecision"],"approved")
                self.assertEqual(a["reviewedBy"],"independent-official-verifier")
                self.assertEqual(a["reviewedAt"],"2026-11-02")
                self.assertEqual([x["id"] for x in a["newArtists"]],added)
                proof=a["officialEvidence"][0]
                self.assertEqual(proof["url"],url)
                self.assertEqual(proof["checkedAt"],"2026-11-02")
                fields={"artists","date","venue","genre"}
                if start:fields.add("startTime")
                self.assertTrue(fields.issubset(set(proof["checkedFields"])))
                if ident.endswith("wolves-throne-room"):
                    self.assertIsNone(start)
                    self.assertIn("contradictoires",proof["notes"])
                if ident.endswith("mass-hysteria"):
                    self.assertIn("Complet mais non annulé",proof["notes"])
        venue=next(x for x in self.document["venueApprovals"]
                   if x["venue"]["id"]=="le-forum-vaureal")
        v=venue["venue"]
        self.assertEqual((v["latitude"],v["longitude"]),(49.0313663,2.0218937))
        self.assertEqual(v["address"],"95 boulevard de l'Oise")
        node="https://www.openstreetmap.org/api/0.6/node/4742610793"
        self.assertEqual(v["geoSource"],node)
        self.assertEqual(venue["officialEvidence"][1]["url"],node)
        self.assertEqual(venue["officialEvidence"][1]["proofType"],
                         "openstreetmap-venue-node")

    def test_trabendo_two_reviewed_official_shows_and_way_geo(self):
        rows={a["event"]["id"]:a for a in self.rows}
        expected={
            "go-c-20270122-paris-wage-war":(
                "2027-01-22","Wage War","wage-war",
                "https://www.letrabendo.net/programmation/wage-war/"),
            "go-c-20270203-paris-whitechapel":(
                "2027-02-03","Whitechapel","whitechapel",
                "https://www.letrabendo.net/programmation/whitechapel/"),
        }
        for ident,(date,title,artist,url) in expected.items():
            with self.subTest(ident=ident):
                row=rows[ident]
                event=row["event"]
                self.assertEqual((event["date"],event["title"],
                                  event["artistIds"],event["genres"]),
                                 (date,title,[artist],["Metalcore"]))
                self.assertEqual(event["venueId"],"le-trabendo-paris")
                self.assertIsNone(event["time"])
                self.assertEqual(event["officialUrl"],url)
                self.assertEqual(event["sourceType"],"salle")
                self.assertEqual(row["reviewedAt"],"2026-11-02")
                self.assertEqual(row["reviewedBy"],"independent-official-verifier")
                self.assertEqual([a["id"] for a in row["newArtists"]],[artist])
                self.assertEqual(len(row["officialEvidence"]),1)
                proof=row["officialEvidence"][0]
                self.assertEqual(proof["url"],url)
                self.assertEqual(proof["proofType"],"official-organizer-or-venue")
                self.assertEqual(proof["checkedAt"],"2026-11-02")
                self.assertTrue({"artists","date","venue","genre"}.issubset(
                    set(proof["checkedFields"])))
        v=next(x for x in self.document["venueApprovals"]
               if x["venue"]["id"]=="le-trabendo-paris")
        self.assertEqual((v["venue"]["latitude"],v["venue"]["longitude"]),
                         (48.89265,2.39396))
        self.assertIn("indicatif",v["venue"]["geoPrecision"])
        self.assertEqual(v["venue"]["geoSource"],
           "https://www.openstreetmap.org/api/0.6/way/81704888")
        self.assertEqual(v["officialEvidence"][1]["proofType"],
                         "openstreetmap-venue-way")

    def test_trabendo_four_more_preserve_named_support_and_no_fake_clock(self):
        expected={
            "go-c-20261112-paris-frankie-witch-fingers":(
                "2026-11-12","Frankie and the Witch Fingers + Iguana Death Cult",
                ["frankie-and-the-witch-fingers","iguana-death-cult"],
                ["frankie-and-the-witch-fingers","iguana-death-cult"],
                "Punk Rock","frankie-and-the-witch-fingers"),
            "go-c-20261128-paris-kid-kapichi":(
                "2026-11-28","Kid Kapichi + Demob Happy",
                ["kid-kapichi","demob-happy"],[],
                "Punk Rock","kid-kapichi"),
            "go-c-20270119-paris-comeback-kid":(
                "2027-01-19","Comeback Kid",["comeback-kid"],
                ["comeback-kid"],"Punk Rock","comeback-kid"),
            "go-c-20270606-paris-black-flag":(
                "2027-06-06","Black Flag",["black-flag"],
                ["black-flag"],"Punk Hardcore","black-flag"),
        }
        byid={x["event"]["id"]:x for x in self.rows}
        for ident,(date,title,artists,new,genre,slug) in expected.items():
            with self.subTest(ident=ident):
                a=byid[ident]
                e=a["event"]
                url="https://www.letrabendo.net/programmation/"+slug+"/"
                self.assertEqual((e["date"],e["title"],e["artistIds"],
                                  e["genres"],e["venueId"],e["officialUrl"]),
                    (date,title,artists,[genre],"le-trabendo-paris",url))
                self.assertIsNone(e["time"])
                self.assertEqual(e["sourceType"],"salle")
                self.assertEqual(a["reviewedAt"],"2026-11-02")
                self.assertEqual(a["reviewedBy"],"independent-official-verifier")
                self.assertEqual([x["id"] for x in a["newArtists"]],new)
                self.assertEqual(len(a["officialEvidence"]),1)
                proof=a["officialEvidence"][0]
                self.assertEqual(proof["url"],url)
                self.assertEqual(proof["checkedAt"],"2026-11-02")
                self.assertTrue({"artists","date","venue","genre"}.issubset(
                    set(proof["checkedFields"])))
                self.assertIn("time=null",proof["notes"])

    def test_paris_clubs_three_complete_bills_and_provenance(self):
        expected={
            "go-c-20261110-paris-allt":(
                "2026-11-10","Allt + Avralize + Bite Down",
                "la-maroquinerie-paris",
                ["allt","avralize","bite-down"],
                ["allt","avralize","bite-down"],["Metalcore"]),
            "go-c-20261121-paris-horskh":(
                "2026-11-21","Horskh + We Are Magonia",
                "la-maroquinerie-paris",
                ["horskh","we-are-magonia"],
                ["we-are-magonia"],["Metal industriel"]),
            "go-c-20261115-paris-ice-sealed-eyes":(
                "2026-11-15","Ice Sealed Eyes + Eiga",
                "la-boule-noire-paris",
                ["ice-sealed-eyes","eiga"],["eiga"],
                ["Newcore","Metalcore"]),
        }
        items={x["event"]["id"]:x for x in self.rows}
        for ident,(date,title,venue,artists,new,genres) in expected.items():
            with self.subTest(id=ident):
                self.assertIn(ident,items)
                row=items[ident];e=row["event"]
                self.assertEqual(
                    (e["date"],e["title"],e["venueId"],e["artistIds"],e["genres"]),
                    (date,title,venue,artists,genres))
                self.assertIsNone(e["time"])
                self.assertEqual(e["sourceType"],"salle")
                self.assertEqual(row["reviewedBy"],"independent-official-verifier")
                self.assertEqual(row["reviewedAt"],"2026-11-02")
                self.assertEqual([x["id"] for x in row["newArtists"]],new)
                self.assertEqual(row["officialEvidence"][0]["url"],e["officialUrl"])
                self.assertEqual(row["officialEvidence"][0]["checkedAt"],"2026-11-02")
        horskh=items["go-c-20261121-paris-horskh"]
        self.assertEqual(len(horskh["officialEvidence"]),2)
        self.assertEqual(
            [x["proofType"] for x in horskh["officialEvidence"]],
            ["official-organizer-or-venue","first-party-venue-calendar"])
        self.assertNotIn("date",horskh["officialEvidence"][0]["checkedFields"])
        self.assertIn("date",horskh["officialEvidence"][1]["checkedFields"])
        venues={x["venue"]["id"]:x for x in self.document["venueApprovals"]}
        self.assertEqual((venues["la-maroquinerie-paris"]["venue"]["latitude"],
                          venues["la-maroquinerie-paris"]["venue"]["longitude"]),
                         (48.86853,2.39206))
        self.assertEqual((venues["la-boule-noire-paris"]["venue"]["latitude"],
                          venues["la-boule-noire-paris"]["venue"]["longitude"]),
                         (48.88234,2.34028))
        for key in ("la-maroquinerie-paris","la-boule-noire-paris"):
            self.assertEqual(venues[key]["officialEvidence"][1]["proofType"],
                             "openstreetmap-venue-node")

    def test_joker_official_bills_and_start_times_are_separate_from_doors(self):
        expected={
            "go-c-20261127-angers-charles-de-goal":("2026-11-27","21:00",["charles-de-goal"]),
            "go-c-20261211-angers-aurore-brutaliste":("2026-12-11","20:30",["aurore","brutaliste"])
        }
        byid={r["event"]["id"]:r for r in self.rows}
        for key,(date,time,artists) in expected.items():
            with self.subTest(key=key):
                self.assertIn(key,byid)
                r=byid[key]; e=r["event"]
                self.assertEqual(e["date"],date)
                self.assertEqual(e["time"],time)
                self.assertEqual(e["venueId"],"jokers-pub-angers")
                self.assertEqual(e["artistIds"],artists)
                self.assertTrue(e["officialUrl"].startswith(
                    "https://www.jokerspubangers.com/jokers-concert-programmation-"))
                self.assertEqual(
                    {a["id"] for a in r["newArtists"]},set(artists))
                self.assertTrue({"date","artists","genre","venue","startTime"}.issubset(
                    set(r["officialEvidence"][0]["checkedFields"])))


    def test_brin_independently_reviewed_organizer_submitted_announcements(self):
        expected={
            "2026-11-05":("noveria","tarchon-fist","wedingoth"),
            "2026-11-09":("fvzz-popvli",),
            "2026-11-12":("ancient-settlers",),
            "2026-11-15":("moscow-death-brigade",),
        }
        rows=[x for x in self.rows
              if x["event"]["venueId"]=="le-brin-de-zinc-barberaz"
              and x["event"]["date"] in expected]
        self.assertEqual(len(rows),len(expected))
        for r in rows:
            e=r["event"]
            with self.subTest(date=e["date"]):
                self.assertEqual(tuple(e["artistIds"]),expected[e["date"]])
                self.assertIsNone(e["time"])
                self.assertEqual(e["sourceType"],"organisateur")
                self.assertEqual(e["status"],"confirmed")
                self.assertEqual(r["reviewedBy"],"independent-official-verifier")
                self.assertEqual(e["ticketUrl"],e["officialUrl"])
                self.assertEqual(len(r["officialEvidence"]),2)
                ticket,partner=r["officialEvidence"]
                self.assertTrue(ticket["url"].startswith("https://www.billetweb.fr/"))
                self.assertEqual(ticket["url"],e["officialUrl"])
                self.assertEqual(ticket["proofType"],"official-organizer-or-venue")
                self.assertEqual(partner["proofType"],"organizer-submitted-partner")
                self.assertTrue(partner["url"].startswith(
                    "https://www.culturesducoeur.org/Home/evenement_look?id_evenement="))
                for source in (ticket,partner):
                    self.assertEqual(source["checkedAt"],"2026-11-02")
                    self.assertTrue({"artists","date","venue","genre"}.issubset(
                        set(source["checkedFields"])))


    def test_two_new_brin_dates_are_individually_cross_checked_not_auto_generated(self):
        expected={
            "go-c-20261110-barberaz-wake-the-dead":(
                "2026-11-10","Wake the Dead + Ghouldozer",
                ["wake-the-dead","ghouldozer"],["ghouldozer"],
                "https://www.billetweb.fr/wake-the-dead-ft-ghouldozer-hardcore-death-metal",
                "artist-event-listing"),
            "go-c-20261206-barberaz-xaon":(
                "2026-12-06","Xaon + Vortex",
                ["xaon","vortex"],["xaon","vortex"],
                "https://www.billetweb.fr/xaon-x-vortex-symphonic-death-metal-canada",
                "independent-tour-report"),
        }
        byid={r["event"]["id"]:r for r in self.rows}
        for ident,(date,title,artists,new,url,secondary_kind) in expected.items():
            with self.subTest(id=ident):
                row=byid[ident]
                e=row["event"]
                self.assertEqual((e["date"],e["title"],e["artistIds"]),
                                 (date,title,artists))
                self.assertEqual(e["venueId"],"le-brin-de-zinc-barberaz")
                self.assertEqual(e["officialUrl"],url)
                self.assertEqual(e["ticketUrl"],url)
                self.assertEqual(e["sourceType"],"organisateur")
                self.assertEqual(e["time"],None)  # Billetterie != début du concert.
                self.assertEqual(row["reviewedBy"],"independent-official-verifier")
                self.assertEqual(row["reviewedAt"],"2026-11-02")
                self.assertEqual([x["id"] for x in row["newArtists"]],new)
                self.assertEqual(len(row["officialEvidence"]),2)
                first,second=row["officialEvidence"]
                self.assertEqual(first["url"],url)
                self.assertEqual(first["proofType"],"official-organizer-or-venue")
                self.assertEqual(second["proofType"],secondary_kind)
                self.assertNotEqual(second["url"],url)
                for proof in row["officialEvidence"]:
                    self.assertEqual(proof["checkedAt"],"2026-11-02")
                    self.assertTrue({"artists","date","venue"}.issubset(
                                    proof["checkedFields"]))
                self.assertIn("genre",first["checkedFields"])

    def test_only_one_historical_lineup_correction_with_named_evidence(self):
        rows=self.document.get("referenceCorrections",[])
        self.assertEqual(len(rows),1)
        item=rows[0]
        self.assertEqual(item["eventId"],"go-c-20261212-nantes-lost-in-kyiv")
        self.assertEqual(item["reviewDecision"],"approved")
        self.assertEqual(item["reviewedBy"],"independent-official-verifier")
        self.assertEqual(item["eventPatch"],{
            "title":"Lost in Kyiv + Årabrot",
            "artistIds":["lost-in-kyiv","arabrot"],
            "lastVerified":"2026-11-02"})
        self.assertEqual(len(item["officialEvidence"]),1)
        evidence=item["officialEvidence"][0]
        self.assertEqual(evidence["url"],
            "https://www.leferrailleur.fr/evenement/lost-in-kyiv/5307")
        self.assertEqual(evidence["checkedAt"],"2026-11-02")
        self.assertEqual(evidence["proofType"],"official-venue-detail")
        self.assertTrue({"artists","date","venue","startTime"}.issubset(
            set(evidence["checkedFields"])))

    def test_backstage_geo_is_the_named_theatre_node_not_adjacent_pub(self):
        rows=[x for x in self.document.get("venueApprovals",[])
              if x.get("venue",{}).get("id")=="backstage-by-the-mill-paris"]
        self.assertEqual(len(rows),1)
        item=rows[0]
        self.assertEqual(item["reviewedBy"],"independent-official-verifier")
        geo=item["venue"]
        self.assertEqual((geo["latitude"],geo["longitude"]),(48.8842402,2.3321006))
        self.assertEqual(geo["address"],"92 bis boulevard de Clichy")
        self.assertEqual(geo["geoSource"],"https://www.openstreetmap.org/api/0.6/node/4428897899")
        self.assertEqual([e["proofType"] for e in item["officialEvidence"]],
                         ["official-venue-address","openstreetmap-venue-node"])
        self.assertEqual(item["officialEvidence"][1]["url"],
                         "https://www.openstreetmap.org/api/0.6/node/4428897899")

    def test_backstage_three_events_exact_artists_dates_and_unknown_clock(self):
        expected={
            "go-c-20270226-paris-turmion-katilot":
                ("2027-02-26","Turmion Kätilöt",["turmion-katilot"],
                 "https://www.backstage-btm.com/agenda/turmion-katilot/"),
            "go-c-20270315-paris-despairsray":
                ("2027-03-15","D’ESPAIRSRAY",["despairsray"],
                 "https://www.backstage-btm.com/agenda/despairsray/"),
            "go-c-20270325-paris-thulcandra":
                ("2027-03-25","Thulcandra + Yoth Iria + Vorga",
                 ["thulcandra","yoth-iria","vorga"],
                 "https://www.backstage-btm.com/agenda/thulcandra-yoth-iria-vorga/"),
        }
        # This historic fixture covers ONLY the three individually signed
        # human reviews. Automated checks can add new Backstage records without
        # invalidating the signatures already verified here.
        selected={e["event"]["id"]:e for e in self.rows
                  if e["event"]["venueId"]=="backstage-by-the-mill-paris"
                  and e["reviewedBy"]=="independent-official-verifier"}
        self.assertEqual(set(selected),set(expected))
        for key,(date,title,artist_ids,url) in expected.items():
            with self.subTest(key=key):
                r=selected[key]
                ev=r["event"]
                self.assertEqual((ev["date"],ev["title"],ev["artistIds"],ev["officialUrl"]),
                                 (date,title,artist_ids,url))
                self.assertIsNone(ev["time"])
                self.assertEqual(ev["status"],"confirmed")
                self.assertEqual(r["reviewedAt"],"2026-11-02")
                self.assertEqual(r["reviewedBy"],"independent-official-verifier")
                self.assertEqual(r["officialEvidence"][0]["url"],url)
                self.assertEqual(r["officialEvidence"][0]["checkedAt"],"2026-11-02")
                self.assertEqual(r["officialEvidence"][0]["proofType"],"official-organizer-or-venue")
                self.assertEqual([a["id"] for a in r["newArtists"]],artist_ids)
                self.assertNotIn("guest",str(ev["artistIds"]).casefold())

    def test_backstage_autorecheck_is_a_distinct_traceable_approval(self):
        ident="go-c-20270219-paris-lost-society"
        matches=[r for r in self.rows if r["event"]["id"]==ident]
        self.assertEqual(len(matches),1)
        r=matches[0]
        event=r["event"]
        url="https://www.backstage-btm.com/agenda/lost-society-hokka/"
        self.assertEqual(r["reviewDecision"],"approved")
        self.assertEqual(r["reviewedBy"],"automated-official-recheck")
        self.assertEqual(r["reviewedAt"],"2026-11-05")
        self.assertEqual(
            (event["title"],event["date"],event["time"],event["artistIds"],
             event["venueId"],event["genres"],event["officialUrl"]),
            ("LOST SOCIETY + HOKKA","2027-02-19",None,
             ["lost-society","hokka"],"backstage-by-the-mill-paris",
             ["Groove Metal"],url))
        self.assertEqual([a["id"] for a in r["newArtists"]],
                         ["lost-society","hokka"])
        self.assertEqual(len(r["officialEvidence"]),1)
        proof=r["officialEvidence"][0]
        self.assertEqual(proof["url"],url)
        self.assertEqual(proof["proofType"],"official-organizer-or-venue")
        self.assertEqual(proof["checkedAt"],"2026-11-05")
        self.assertEqual(proof["checkedFields"],
                         ["artists","date","venue","genre"])
        self.assertEqual(proof["officialArtistNames"],
                         ["LOST SOCIETY","HOKKA"])

    def test_regional_official_2026_approvals_are_exactly_source_backed(self):
        cases={
            "go-c-20261104-lyon-lagrimas-prestige":(
                "2026-11-04","Lagrimas + The Prestige",
                ["lagrimas","the-prestige"],["lagrimas","the-prestige"],
                "rock-n-eat-lyon",
                "https://shotgun.live/events/lagrimas-the-prestige"),
            "go-c-20261111-strasbourg-wake-the-dead":(
                "2026-11-11","Wake the Dead + Toxic Shock + Sick Lame & Lazy",
                ["wake-the-dead","toxic-shock","sick-lame-lazy"],
                ["toxic-shock","sick-lame-lazy"],
                "la-maison-bleue-strasbourg",
                "https://billetterie.lamaisonbleue-stbg.com/share/event/370-Dirty8-Birthday-WAKE-THE-DEAD-SICK-LAME-LAZY"),
            "go-c-20261113-strasbourg-local-heroes":(
                "2026-11-13","Dazzling Bravery + BRDN + Curtains + Foggy Froggies",
                ["dazzling-bravery","brdn","curtains","foggy-froggies"],
                ["dazzling-bravery","brdn","curtains","foggy-froggies"],
                "la-maison-bleue-strasbourg",
                "https://billetterie.lamaisonbleue-stbg.com/share/event/385-Dirty8-Birthday-LOCAL-HEROES-Dazzling-Bravery-BRDN-Curtains-Foggy-Froggies"),
        }
        chosen={x["event"]["id"]:x for x in self.rows
                if x["event"]["venueId"] in
                   ("rock-n-eat-lyon","la-maison-bleue-strasbourg")}
        self.assertEqual(set(chosen),set(cases))
        for event_id,(date,title,artists,new,venue,url) in cases.items():
            with self.subTest(event_id=event_id):
                x=chosen[event_id]
                e=x["event"]
                self.assertEqual((e["date"],e["title"],e["artistIds"],
                                  e["venueId"],e["officialUrl"]),
                                 (date,title,artists,venue,url))
                self.assertEqual(e["time"],None)
                self.assertEqual(e["status"],"confirmed")
                self.assertEqual(x["reviewedBy"],"independent-official-verifier")
                self.assertEqual(x["reviewedAt"],"2026-11-02")
                self.assertEqual([n["id"] for n in x["newArtists"]],new)
                self.assertEqual(len(x["officialEvidence"]),2)
                self.assertEqual(x["officialEvidence"][0]["url"],url)
                self.assertEqual(x["officialEvidence"][0]["proofType"],
                                 "official-organizer-or-venue")
                self.assertEqual(x["officialEvidence"][1]["proofType"],
                                 "first-party-venue-calendar")
                self.assertTrue(all(p["checkedAt"]=="2026-11-02"
                                    for p in x["officialEvidence"]))

    def test_regional_precise_named_osm_points_and_maison_daily_priority(self):
        target={
            "rock-n-eat-lyon":("45.7709758","4.8114869","5973017988"),
            "la-maison-bleue-strasbourg":("48.5595349","7.7680524","7812445394")}
        venues={v["venue"]["id"]:v for v in
                self.document.get("venueApprovals",[])}
        for ident,(lat,lon,node) in target.items():
            with self.subTest(ident=ident):
                v=venues[ident]
                self.assertEqual(str(v["venue"]["latitude"]),lat)
                self.assertEqual(str(v["venue"]["longitude"]),lon)
                osm="https://www.openstreetmap.org/api/0.6/node/"+node
                self.assertEqual(v["venue"]["geoSource"],osm)
                self.assertEqual(v["officialEvidence"][1]["url"],osm)
        sources=json.loads((APPROVALS.parent/"sources.json").read_text(encoding="utf8"))
        maison=next(s for s in sources["venues"]
                    if s["name"]=="La Maison Bleue")
        self.assertEqual(maison["priority"],"P1")
        self.assertFalse(maison["publish_automatically"])

    def test_maison_local_heroes_four_named_artists_and_split_genre_evidence(self):
        key="go-c-20261113-strasbourg-local-heroes"
        by_id=[x for x in self.rows if x["event"]["id"]==key]
        self.assertEqual(len(by_id),1)
        approval=by_id[0]
        event=approval["event"]
        self.assertEqual(event["venueId"],"la-maison-bleue-strasbourg")
        self.assertEqual(event["date"],"2026-11-13")
        self.assertEqual(event["artistIds"],[
            "dazzling-bravery","brdn","curtains","foggy-froggies"
        ])
        self.assertEqual(event["genres"],["Metal"])
        self.assertIsNone(event["time"])
        self.assertEqual(approval["reviewedBy"],"independent-official-verifier")
        self.assertEqual([a["id"] for a in approval["newArtists"]],
                         event["artistIds"])
        self.assertEqual([p["proofType"] for p in approval["officialEvidence"]],
                         ["official-organizer-or-venue","first-party-venue-calendar"])
        self.assertEqual(set(approval["officialEvidence"][0]["checkedFields"]),
                         {"artists","date","venue"})
        self.assertEqual(set(approval["officialEvidence"][1]["checkedFields"]),
                         {"date","venue","genre"})
        self.assertEqual(approval["officialEvidence"][0]["url"],
                         event["officialUrl"])
        self.assertNotIn("genre",approval["officialEvidence"][0]["checkedFields"])
        self.assertNotIn("artists",approval["officialEvidence"][1]["checkedFields"])

    def test_glazart_named_building_and_two_complete_individual_lineups(self):
        venues=[a for a in self.document.get("venueApprovals",[])
                if a.get("venue",{}).get("id")=="glazart-paris"]
        self.assertEqual(len(venues),1)
        row=venues[0]
        v=row["venue"]
        self.assertEqual(v["address"],"7–15 avenue de la Porte de la Villette")
        self.assertEqual((v["latitude"],v["longitude"]),(48.899283,2.3866102))
        osm="https://www.openstreetmap.org/api/0.6/way/64038567"
        self.assertEqual(v["geoSource"],osm)
        self.assertIn("centre du bâtiment",v["geoPrecision"])
        self.assertEqual(row["officialEvidence"][1]["proofType"],
                         "openstreetmap-venue-way")
        self.assertEqual(row["officialEvidence"][1]["url"],osm)
        expected={
            "go-c-20261128-paris-sunami":(
                "2026-11-28",
                ["sunami","desolated","missing-link","extinguish"],
                [],
                "https://www.glazart.com/28-11-26-concert-sunami-missing-link-extinguish/"),
            "go-c-20270324-paris-party-cannon":(
                "2027-03-24",
                ["party-cannon","internal-bleeding","guttural-slug"],
                ["party-cannon","internal-bleeding","guttural-slug"],
                "https://www.glazart.com/24-03-27-concert-party-cannon-x-internal-bleeding/"),
            "go-c-20261106-paris-lagrimas":(
                "2026-11-06",["lagrimas"],[],
                "https://www.glazart.com/06-11-26-concert-lagrimas/"),
            "go-c-20261130-paris-black-sabbitch":(
                "2026-11-30",["black-sabbitch"],["black-sabbitch"],
                "https://www.glazart.com/30-11-26-concert-black-sabbitch/"),
            "go-c-20261104-paris-eyehategod":(
                "2026-11-04",["eyehategod","deafkids"],["eyehategod","deafkids"],
                "https://www.glazart.com/04-11-26-concert-eyehategod-guest/"),
            "go-c-20261114-paris-the-vintage-caravan":(
                "2026-11-14",["the-vintage-caravan","damantra"],[],
                "https://www.glazart.com/14-11-26-concert-the-vintage-caravan/"),
        }
        bills={a["event"]["id"]:a for a in self.rows
               if a["event"]["venueId"]=="glazart-paris"}
        # Additional approved Glazart bills are tested by their own signed lot.
        self.assertTrue(set(expected).issubset(set(bills)))
        for key,(date,ids,added,url) in expected.items():
            with self.subTest(id=key):
                record=bills[key]
                event=record["event"]
                self.assertEqual(event["date"],date)
                self.assertEqual(event["artistIds"],ids)
                self.assertIsNone(event["time"])
                self.assertEqual(event["status"],"confirmed")
                self.assertEqual(event["officialUrl"],url)
                self.assertEqual([a["id"] for a in record["newArtists"]],added)
                self.assertEqual(record["reviewedBy"],"independent-official-verifier")
                self.assertEqual(record["officialEvidence"][0]["url"],url)
                fields=({"leadArtist","date","venue","genre"}
                    if key=="go-c-20261114-paris-the-vintage-caravan"
                    else {"artists","date","venue","genre"})
                self.assertTrue(fields.issubset(
                    set(record["officialEvidence"][0]["checkedFields"])))


    def test_glazart_two_new_verified_bills_do_not_promote_guest_to_artist(self):
        rows={x["event"]["id"]:x for x in self.rows}
        eye=rows["go-c-20261104-paris-eyehategod"]
        vin=rows["go-c-20261114-paris-the-vintage-caravan"]
        self.assertEqual(eye["event"]["title"],"Eyehategod + Deafkids")
        self.assertEqual(eye["event"]["genres"],["Sludge","Avant-Punk"])
        self.assertEqual(eye["newArtists"],[
            {"id":"eyehategod","name":"Eyehategod"},
            {"id":"deafkids","name":"Deafkids"}])
        self.assertEqual(vin["event"]["title"],"The Vintage Caravan + Damantra")
        self.assertEqual(vin["event"]["genres"],["Classic Rock"])
        self.assertEqual(vin["newArtists"],[])
        self.assertEqual(vin["officialEvidence"][1]["url"],
            "https://billetterie.seetickets.fr/the-vintage-caravan-damantra-concert-glazart-paris-19-14-novembre-2026-css5-garmonbozia-pg101-ri11777349.html")
        self.assertEqual(vin["officialEvidence"][1]["proofType"],
                         "organizer-ticketing-detail")
        self.assertNotIn("guest",str(eye["event"]["artistIds"]).lower())
        self.assertNotIn("guest",str(vin["event"]["artistIds"]).lower())
        self.assertTrue(all(a["event"]["time"] is None for a in (eye,vin)))
        self.assertTrue(all(a["reviewedAt"]=="2026-11-02" for a in (eye,vin)))

    def test_glazart_two_new_november_bills_have_separate_dates_and_genres(self):
        a={x["event"]["id"]:x for x in self.rows}
        lag=a["go-c-20261106-paris-lagrimas"]
        sab=a["go-c-20261130-paris-black-sabbitch"]
        self.assertEqual(lag["event"]["genres"],["Hardcore","Screamo"])
        self.assertEqual(sab["event"]["genres"],["Doom"])
        self.assertEqual(lag["event"]["date"],"2026-11-06")
        self.assertEqual(sab["event"]["date"],"2026-11-30")
        self.assertEqual(lag["event"]["artistIds"],["lagrimas"])
        self.assertEqual(sab["event"]["artistIds"],["black-sabbitch"])
        self.assertEqual(lag["newArtists"],[])
        self.assertEqual(sab["newArtists"],[
            {"id":"black-sabbitch","name":"Black Sabbitch"}])
        self.assertIsNone(lag["event"]["time"])
        self.assertIsNone(sab["event"]["time"])
        self.assertEqual(sab["officialEvidence"][0]["url"],
                         "https://www.glazart.com/30-11-26-concert-black-sabbitch/")
        self.assertTrue(all(x["reviewedBy"]=="independent-official-verifier"
                            and x["reviewedAt"]=="2026-11-02" for x in (lag,sab)))


    def test_rex_gps_correction_has_signed_official_coords_and_independent_address(self):
        corrections=self.document.get("referenceVenueCorrections",[])
        self.assertEqual({x["venueId"] for x in corrections},{
            "secret-place-saint-jean-de-vedas","le-rex-toulouse",
            "le-bikini-toulouse","rockstore-montpellier",
            "the-black-lab-wasquehal","antipode-rennes",
            "zenith-paris-la-villette-paris", "le-transbordeur-villeurbanne",
            "la-belle-electrique-grenoble","l-autre-canal-nancy"
        })
        self.assertEqual(len(corrections),10)
        rex=next(x for x in corrections if x["venueId"]=="le-rex-toulouse")
        self.assertEqual((rex["reviewDecision"],rex["reviewedBy"],rex["reviewedAt"]),
                         ("approved","independent-official-verifier","2026-11-03"))
        self.assertEqual(rex["venuePatch"],{
            "address":"15 avenue Honoré Serres",
            "postalCode":"31000",
            "latitude":43.611901,
            "longitude":1.438364,
            "geoPrecision":"GPS publié par Le Rex (localisation de la salle, entrée non garantie)",
            "geoSource":"https://www.lerextoulouse.com/fr/contact/acces/",
        })
        self.assertEqual({
            (x["proofType"],x["url"]) for x in rex["officialEvidence"]
        },{
            ("official-venue-gps","https://www.lerextoulouse.com/fr/contact/acces/"),
            ("tourism-office-address",
             "https://www.toulouse-tourisme.com/activite/le-rex-de-toulouse/"),
        })
        self.assertTrue(all(x["checkedAt"]=="2026-11-03"
                            for x in rex["officialEvidence"]))
        self.assertGreaterEqual(len(self.rows),86)
        self.assertLessEqual(len(self.rows), 400)


    def test_laiterie_nine_signed_records_use_only_confirmed_artist_ids_and_door_times_unknown(self):
        newly=[r for r in self.rows if r["event"]["venueId"]=="la-laiterie-strasbourg"
               and r["event"]["id"].startswith("go-c-2027")
               and r["reviewedAt"]=="2026-11-03" and not r["newArtists"]]
        self.assertEqual(len(newly),9)
        self.assertEqual(len({r["event"]["id"] for r in newly}),9)
        expected={
            "2027-02-05","2027-02-09","2027-02-14","2027-02-16",
            "2027-03-06","2027-03-09","2027-03-16","2027-03-26","2027-09-09"
        }
        self.assertEqual({r["event"]["date"] for r in newly},expected)
        for row in newly:
            self.assertEqual(row["reviewDecision"],"approved")
            self.assertEqual(row["reviewedBy"],"independent-official-verifier")
            self.assertIsNone(row["event"]["time"])
            self.assertEqual(row["newArtists"],[])
            self.assertEqual(row["event"]["status"],"confirmed")
            self.assertEqual(len(row["officialEvidence"]),2)
            self.assertEqual(
                {p["proofType"] for p in row["officialEvidence"]},
                {"official-organizer-or-venue","first-party-venue-calendar"}
            )
            for proof in row["officialEvidence"]:
                self.assertEqual(proof["checkedAt"],"2026-11-03")
                self.assertNotIn("startTime",proof["checkedFields"])
            self.assertTrue(row["event"]["officialUrl"].startswith(
                "https://www.artefact.org/la-laiterie/evenements/"))



    def test_laiterie_five_extra_exact_new_artists_are_listed_and_not_fake_times(self):
        events=[r for r in self.rows if r["event"]["venueId"]=="la-laiterie-strasbourg"
                and r["newArtists"] and r["reviewedAt"]=="2026-11-03"
                and r["event"]["date"] in {"2026-12-05","2026-12-18",
                     "2027-02-17","2027-02-24","2027-04-04","2027-04-22"}]
        self.assertEqual(len(events),6)
        self.assertEqual(sum(len(r["newArtists"]) for r in events),14)
        self.assertEqual(
            {r["event"]["date"] for r in events},
            {"2026-12-05","2026-12-18","2027-02-17","2027-02-24","2027-04-04","2027-04-22"}
        )
        newIds=[n["id"] for row in events for n in row["newArtists"]]
        self.assertEqual(len(newIds),len(set(newIds)))
        for row in events:
            self.assertIsNone(row["event"]["time"])
            self.assertEqual(row["reviewDecision"],"approved")
            self.assertEqual(row["reviewedBy"],"independent-official-verifier")
            expectedProofs=3 if row["event"]["id"]=="go-c-20270217-strasbourg-sleeping-with-sirens" else 2
            self.assertEqual(len(row["officialEvidence"]),expectedProofs)
            self.assertTrue(all(p["checkedAt"]=="2026-11-03"
                                and "startTime" not in p["checkedFields"]
                                for p in row["officialEvidence"]))
            self.assertTrue(row["event"]["officialUrl"].startswith(
                "https://www.artefact.org/la-laiterie/evenements/"))


    def test_sleeping_with_sirens_correct_name_comes_from_independent_promoter(self):
        record=next(x for x in self.rows
            if x["event"]["id"]=="go-c-20270217-strasbourg-sleeping-with-sirens")
        self.assertEqual(record["event"]["title"],
            "Sleeping With Sirens + Arm's Length + Like Roses")
        self.assertEqual(record["newArtists"],[
            {"id":"sleeping-with-sirens","name":"Sleeping With Sirens"},
            {"id":"arms-length","name":"Arm's Length"},
            {"id":"like-roses","name":"Like Roses"}
        ])
        self.assertIsNone(record["event"]["time"])
        source=next(x for x in record["officialEvidence"]
                    if x["proofType"]=="independent-organizer-confirmation")
        self.assertEqual(source["url"],
            "https://www.livenation.com/event/intl_1673680/sleeping-with-sirens-an-ending-in-itself-tour")
        self.assertEqual(source["checkedAt"],"2026-11-03")
        self.assertEqual(set(source["checkedFields"]),{"artists","date","venue"})

if __name__=="__main__":
    unittest.main()
