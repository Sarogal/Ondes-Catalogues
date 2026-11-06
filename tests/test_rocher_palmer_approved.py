"""Strict tests for the seven signed Rocher de Palmer event records (no network)."""
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
}
VENUES = {"le-rocher-de-palmer-cenon": {
    "id":"le-rocher-de-palmer-cenon",
    "name":"Le Rocher de Palmer","city":"Cenon",
}}
FRESH = {"tagada-jones":"Tagada Jones","die-arzte":"Die Ärzte",
         "gwendoline":"Gwendoline","bleu-panique":"Bleu Panique"}


def approval(event_id):
    s=sync.ROCHER_PALMER_VERIFIED[event_id]
    checked="2026-11-06" if event_id=="go-c-20261107-cenon-gwendoline" else "2026-11-02"
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
        self.assertEqual(len(sync.ROCHER_PALMER_VERIFIED),7)
        for event_id in sync.ROCHER_PALMER_VERIFIED:
            with self.subTest(event_id=event_id):
                event,artists=sync.validate_approval(approval(event_id),VENUES,KNOWN,TODAY)
                self.assertEqual(event["venueId"],"le-rocher-de-palmer-cenon")
                self.assertEqual(set(artists),set(x["id"] for x in approval(event_id)["newArtists"]))

    def test_gwendoline_officially_named_support_and_canonicals(self):
        event_id="go-c-20261107-cenon-gwendoline"
        reviewed=approval(event_id)
        self.assertEqual(reviewed["reviewedAt"],"2026-11-06")
        event,added=sync.validate_approval(reviewed,VENUES,KNOWN,TODAY)
        self.assertEqual(event["title"],"Gwendoline + Bleu Panique")
        self.assertEqual(event["artistIds"],["gwendoline","bleu-panique"])
        self.assertEqual(event["date"],"2026-11-07")
        self.assertEqual(event["time"],"20:30")
        self.assertEqual(set(added),{"gwendoline","bleu-panique"})
        for change in ("dropped-support","wrong-support","invented-time"):
            a=approval(event_id)
            if change=="dropped-support":
                a["event"]["artistIds"]=["gwendoline"]
            elif change=="wrong-support":
                a["newArtists"][1]["name"]="Unknown Performer"
            elif change=="invented-time":
                a["event"]["time"]="19:30"
            with self.subTest(change=change),self.assertRaises(ValueError):
                sync.validate_approval(a,VENUES,KNOWN,TODAY)

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
