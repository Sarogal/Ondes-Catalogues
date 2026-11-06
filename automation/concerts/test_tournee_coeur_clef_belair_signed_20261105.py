"""Revue signée de deux lieux et dates Tournée du Cœur (La CLEF + Bel Air)."""
import copy
import json
import unittest
from pathlib import Path

DATA=json.loads((Path(__file__).parent/"approved.json").read_text(encoding="utf-8"))
CHECKED="2026-11-05"
ARTISTS=["cachemire","la-phaze","bobs-not-dead"]
BILL=["Cachemire","La Phaze","Bob's Not Dead"]
EXPECTED={
 "go-c-20270129-saint-germain-en-laye-cachemire-la-phaze-bobs-not-dead":(
  "2027-01-29","20:30","la-clef-saint-germain-en-laye",
  "https://laclef.asso.fr/evenement/la-tournee-du-coeur-cachemire-la-phaze-bobs-not-dead/",
  "https://www.cachemiremusic.fr/concerts.html",
  "official-artist-tour-calendar","La CLEF"),
 "go-c-20270212-saint-aubin-du-cormier-cachemire-la-phaze-bobs-not-dead":(
  "2027-02-12","20:30","espace-bel-air-saint-aubin-du-cormier",
  "https://espacebelair.net/laffiche/saison-culturelle-2026-2027/",
  "https://www.saint-aubin-du-cormier.bzh/evenement/tournee-du-coeur-iii-cachemire-la-phaze-bobs-not-dead/",
  "first-party-municipal-event-calendar","Espace Bel Air / Saint-Aubin-du-Cormier"),
}
VENUES={
 "la-clef-saint-germain-en-laye":(
  "La CLEF","46 rue de Mareil","78100","Saint-Germain-en-Laye",
  48.89409,2.08842,
  "https://laclef.asso.fr/infos-pratiques/comment-venir/",
  "https://musitree.fr/concerts/salles/la-clef-saint-germain-en-laye-saint-germain-en-laye/",
  "independent-named-venue-geolocation"),
 "espace-bel-air-saint-aubin-du-cormier":(
  "Espace Bel Air","rue des Rochers","35140","Saint-Aubin-du-Cormier",
  48.25787,-1.38968,
  "https://espacebelair.net/info-pratiques/",
  "https://mapcarta.com/fr/W117002146","openstreetmap-venue-way"),
}

def verify_event(row, ident):
    date,time,venue,url,secondary,proof_kind,organizer=EXPECTED[ident]
    exact={"id":ident,"title":"Cachemire + La Phaze + Bob's Not Dead",
      "date":date,"time":time,"artistIds":ARTISTS,"venueId":venue,
      "genres":["Rock","Punk"],"status":"confirmed","officialUrl":url,
      "sourceType":"salle","organizer":organizer}
    if (row.get("reviewDecision")!="approved" or
        row.get("reviewedBy")!="independent-official-verifier" or
        row.get("reviewedAt")!=CHECKED or row.get("event")!=exact or
        row.get("newArtists")!=[]):
        raise ValueError("Fiche non signée")
    evidence=row.get("officialEvidence")
    if not isinstance(evidence,list) or len(evidence)!=2:
        raise ValueError("Preuves manquantes")
    first,second=evidence
    if (first.get("url")!=url or
        first.get("proofType")!="official-organizer-or-venue" or
        first.get("checkedAt")!=CHECKED or
        first.get("confirmedArtists")!=BILL or
        "concertStartTime" not in first.get("checkedFields",[]) or
        first.get("concertStartTimeConfirmed")!=time or
        second.get("url")!=secondary or second.get("proofType")!=proof_kind or
        second.get("checkedAt")!=CHECKED or
        not {"artists","date","venue","genre"}.issubset(
          set(first.get("checkedFields",[])))):
        raise ValueError("Preuve concert fausse")
    return True

def verify_venue(row, ident):
    name,address,post,city,lat,lon,official,geo,kind=VENUES[ident]
    venue=row.get("venue") or {}
    if (row.get("reviewDecision")!="approved" or
        row.get("reviewedBy")!="independent-official-verifier" or
        row.get("reviewedAt")!=CHECKED or
        (venue.get("id"),venue.get("name"),venue.get("address"),
         venue.get("postalCode"),venue.get("city"),
         venue.get("latitude"),venue.get("longitude"),
         venue.get("geoSource")) !=
        (ident,name,address,post,city,lat,lon,geo) or
        "indicatif" not in venue.get("geoPrecision","").lower()):
        raise ValueError("Lieu/GPS altéré")
    proofs=row.get("officialEvidence")
    if not isinstance(proofs,list) or len(proofs)!=2:
        raise ValueError("Preuves lieu manquantes")
    if not (proofs[0].get("url")==official and
        proofs[0].get("proofType")=="official-venue-address" and
        proofs[1].get("url")==geo and proofs[1].get("proofType")==kind and
        all(x.get("checkedAt")==CHECKED for x in proofs)):
        raise ValueError("Preuves GPS non conformes")
    return True

class CoeurClefBelAirSigned(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events={x["event"]["id"]:x for x in DATA["approvals"]}
        cls.venues={x["venue"]["id"]:x for x in DATA["venueApprovals"]}

    def test_signature(self):
        self.assertEqual(len(self.events),len(DATA["approvals"]))
        self.assertEqual(len(self.venues),len(DATA["venueApprovals"]))
        for key in EXPECTED:
            self.assertTrue(verify_event(self.events[key],key))
        for key in VENUES:
            self.assertTrue(verify_venue(self.venues[key],key))

    def test_mutations(self):
        for key in EXPECTED:
            for how,fn in [
                ("date",lambda x:x["event"].update(date="2027-02-25")),
                ("time",lambda x:x["event"].update(time="19:00")),
                ("artist",lambda x:x["event"]["artistIds"].append("ghost")),
                ("url",lambda x:x["officialEvidence"][0].update(url="https://example.org")),
                ("tour",lambda x:x["officialEvidence"][1].update(url="https://example.org")),
                ("start",lambda x:x["officialEvidence"][0].update(concertStartTimeConfirmed="19:00")),
                ("reviewer",lambda x:x.update(reviewedBy="automated-official-recheck")),
            ]:
                row=copy.deepcopy(self.events[key]);fn(row)
                with self.subTest(id=key,what=how),self.assertRaises(ValueError):
                    verify_event(row,key)
        for key in VENUES:
            for how,fn in [
                ("geo",lambda x:x["venue"].update(latitude=42.0)),
                ("street",lambda x:x["venue"].update(address="inconnue")),
                ("proof",lambda x:x["officialEvidence"][1].update(url="https://example.org")),
            ]:
                row=copy.deepcopy(self.venues[key]);fn(row)
                with self.subTest(id=key,what=how),self.assertRaises(ValueError):
                    verify_venue(row,key)

if __name__=="__main__":
    unittest.main()
