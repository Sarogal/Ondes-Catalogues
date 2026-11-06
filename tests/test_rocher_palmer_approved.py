"""Strict tests for eight signed Rocher de Palmer concert records (no network)."""
import copy
import datetime as dt
import unittest
from scripts import concerts_cloud_sync as sync

TODAY = dt.date(2026, 11, 6)
KNOWN = {
    "les-tambours-du-bronx": {"id":"les-tambours-du-bronx","name":"Les Tambours du Bronx"},
    "rhapsody-of-fire": {"id":"rhapsody-of-fire","name":"Rhapsody of Fire"},
    "serious-black": {"id":"serious-black","name":"Serious Black"},
    "ugly-kid-joe": {"id":"ugly-kid-joe","name":"Ugly Kid Joe"},
    "m-l": {"id":"m-l","name":"MØL"},
    "uuhai": {"id":"uuhai","name":"Uuhai"},
    "acyl": {"id":"acyl","name":"Acyl"},
    "the-stranglers": {"id":"the-stranglers","name":"The Stranglers"},
}
VENUES = {"le-rocher-de-palmer-cenon": {
    "id":"le-rocher-de-palmer-cenon",
    "name":"Le Rocher de Palmer","city":"Cenon",
}}
FRESH = {"tagada-jones":"Tagada Jones","die-arzte":"Die Ärzte",
         "gwendoline":"Gwendoline","bleu-panique":"Bleu Panique",
         "brother-junior":"Brother Junior"}


def approval(event_id):
    s=sync.ROCHER_PALMER_VERIFIED[event_id]
    checked = "2026-11-06" if event_id == "go-c-20261107-cenon-gwendoline" else "2026-11-02"
    if event_id == "go-c-20261124-cenon-the-stranglers":
        return {
            "reviewDecision": "approved",
            "reviewedBy": "independent-official-verifier",
            "reviewedAt": "2026-11-06",
            "officialEvidence": [
                {
                    "url": s["officialUrl"],
                    "proofType": "official-organizer-or-venue",
                    "checkedAt": "2026-11-06",
                    "checkedFields": ["artists", "date", "venue", "genre",
                                      "startTime", "doorTime"],
                    "officialArtistNames": ["The Stranglers", "Brother Junior"],
                    "concertStartTimeConfirmed": "20:30",
                    "doorTimeConfirmed": "19:30",
                },
                {
                    "url": "https://billetterie.lerocherdepalmer.fr/agenda/1862-THE-STRANGLERS?session=1862",
                    "proofType": "first-party-venue-ticketing",
                    "checkedAt": "2026-11-06",
                    "checkedFields": ["artists", "date", "venue"],
                    "officialArtistNames": ["The Stranglers", "Brother Junior"],
                },
            ],
            "event": {
                "id": event_id, "title": s["title"], "date": s["date"],
                "time": s["time"], "artistIds": list(s["artistIds"]),
                "venueId": "le-rocher-de-palmer-cenon", "genres": list(s["genres"]),
                "status": "confirmed", "officialUrl": s["officialUrl"],
                "sourceType": "salle", "organizer": "Le Rocher de Palmer",
            },
            "newArtists": [{"id": "brother-junior", "name": "Brother Junior"}],
        }
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":checked,
        "officialEvidence":[{
            "url":s["officialUrl"],"proofType":"official-organizer-or-venue",
            "checkedAt":checked,
            "checkedFields":["artists","date","venue","genre","startTime"],
            "notes":"Named headliners, date, salle and advertised start confirmed on first-party event detail."
        }],
        "event":{
            "id":event_id,"title":s["title"],"date":s["date"],
            "time":s["time"],"artistIds":list(s["artistIds"]),
            "venueId":"le-rocher-de-palmer-cenon","genres":list(s["genres"]),
            "status":"confirmed","officialUrl":s["officialUrl"],
            "sourceType":"salle","organizer":"Le Rocher de Palmer",
        },
        "newArtists":[{"id":aid,"name":FRESH[aid]} for aid in s["artistIds"] if aid in FRESH]
    }


class RocherPalmerValidation(unittest.TestCase):
    def test_all_seven_individual_official_approvals(self):
        self.assertEqual(len(sync.ROCHER_PALMER_VERIFIED),8)
        for event_id in sync.ROCHER_PALMER_VERIFIED:
            with self.subTest(event_id=event_id):
                event,artists=sync.validate_approval(approval(event_id),VENUES,KNOWN,TODAY)
                self.assertEqual(event["venueId"],"le-rocher-de-palmer-cenon")
                self.assertEqual(set(artists),set(x["id"] for x in approval(event_id)["newArtists"]))


    def test_stranglers_complete_bill_and_existing_artist_is_reused(self):
        identifier = "go-c-20261124-cenon-the-stranglers"
        row = approval(identifier)
        event, artists = sync.validate_approval(row, VENUES, KNOWN, TODAY)
        self.assertEqual(event["title"], "The Stranglers + Brother Junior")
        self.assertEqual(event["date"], "2026-11-24")
        self.assertEqual(event["time"], "20:30")
        self.assertEqual(event["artistIds"], ["the-stranglers", "brother-junior"])
        self.assertEqual(event["genres"], ["Rock"])
        self.assertEqual(list(artists), ["brother-junior"])
        self.assertEqual(row["officialEvidence"][0]["doorTimeConfirmed"], "19:30")
        self.assertEqual(row["officialEvidence"][0]["concertStartTimeConfirmed"], "20:30")

    def test_stranglers_mutated_venue_bill_timing_and_ticketing_are_rejected(self):
        identifier = "go-c-20261124-cenon-the-stranglers"
        for mutation in ("date", "support", "title", "genre", "start", "door",
                         "ticket-url", "ticket-artist", "proof-fields",
                         "reviewer", "source", "missing-ticket", "new-artist",
                         "lead-artist-collision"):
            row = approval(identifier)
            known = copy.deepcopy(KNOWN)
            if mutation == "date":
                row["event"]["date"] = "2026-11-25"
            elif mutation == "support":
                row["event"]["artistIds"] = ["the-stranglers"]
            elif mutation == "title":
                row["event"]["title"] = "The Stranglers"
            elif mutation == "genre":
                row["event"]["genres"] = ["Metal"]
            elif mutation == "start":
                row["event"]["time"] = "19:30"
            elif mutation == "door":
                row["officialEvidence"][0]["doorTimeConfirmed"] = "20:30"
            elif mutation == "ticket-url":
                row["officialEvidence"][1]["url"] = "https://billetterie.evil.example/"
            elif mutation == "ticket-artist":
                row["officialEvidence"][1]["officialArtistNames"][1] = "Other Band"
            elif mutation == "proof-fields":
                row["officialEvidence"][0]["checkedFields"].remove("genre")
            elif mutation == "reviewer":
                row["reviewedBy"] = "automated-official-recheck"
            elif mutation == "source":
                row["event"]["officialUrl"] = "https://other.example/concert"
            elif mutation == "missing-ticket":
                row["officialEvidence"].pop()
            elif mutation == "new-artist":
                row["newArtists"][0]["name"] = "Unknown"
            elif mutation == "lead-artist-collision":
                known["the-stranglers"]["name"] = "Wrong name"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                sync.validate_approval(row, VENUES, known, TODAY)

    def test_mutations_are_never_an_approval(self):
        event_id="go-c-20270326-cenon-uuhai"
        for mutation in ("date","title","startTime","genre","url","source","reviewer","proof","age"):
            a=approval(event_id)
            if mutation=="date": a["event"]["date"]="2027-03-25"
            if mutation=="title": a["event"]["title"]="Another act"
            if mutation=="startTime": a["event"]["time"]="18:30"
            if mutation=="genre": a["event"]["genres"]=["Pop"]
            if mutation=="url": a["event"]["officialUrl"]="https://other.example/agenda/uuhai"
            if mutation=="source": a["event"]["sourceType"]="organisateur"
            if mutation=="reviewer": a["reviewedBy"]="automated-official-recheck"
            if mutation=="proof": a["officialEvidence"][0]["checkedFields"].remove("startTime")
            if mutation=="age": a["reviewedAt"]="2026-10-12"
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                sync.validate_approval(a,VENUES,KNOWN,TODAY)

    def test_venue_and_new_artist_identity_not_invented(self):
        a=approval("go-c-20261121-cenon-tagada-jones")
        a["newArtists"][0]["name"]="Other Artist"
        with self.assertRaises(ValueError):
            sync.validate_approval(a,VENUES,KNOWN,TODAY)
        a=approval("go-c-20261121-cenon-tagada-jones")
        a["event"]["venueId"]="a-nonexistent-venue"
        with self.assertRaises(ValueError):
            sync.validate_approval(a,VENUES,KNOWN,TODAY)

    def test_unauthorized_event_at_same_venue_is_rejected(self):
        a=approval("go-c-20270326-cenon-uuhai")
        a["event"]["id"]="go-c-20270327-cenon-uuhai"
        with self.assertRaises(ValueError):
            sync.validate_approval(a,VENUES,KNOWN,TODAY)

if __name__=="__main__":
    unittest.main()
