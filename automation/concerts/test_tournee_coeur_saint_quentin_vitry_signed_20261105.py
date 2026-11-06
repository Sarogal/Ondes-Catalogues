"""Auditer signatures privées nominatives du 4 et 5 février 2027."""
import copy
import json
import unittest
from pathlib import Path

DOC = json.loads((Path(__file__).parent/"approved.json").read_text(encoding="utf-8"))
DAY = "2026-11-05"
TOUR = "https://tourneeducoeur.ragetour.com/"
BILL = ["cachemire", "la-phaze", "bobs-not-dead"]
ARTISTS = ["Cachemire", "La Phaze", "Bob's Not Dead"]
SPECS = {
 "go-c-20270204-saint-quentin-cachemire-la-phaze-bobs-not-dead": {
  "date":"2027-02-04","time":None,"venueId":"la-manufacture-saint-quentin",
  "officialUrl":"https://billetterie-saint-quentin.mapado.com/en/event/756872-la-tournee-du-coeur",
  "organizer":"Rage Tour / Ville de Saint-Quentin",
  "proofType":"official-organizer-or-venue",
  "checkedFields":["artists","date","venue","genre","ticketTime"],
 },
 "go-c-20270205-vitry-le-francois-cachemire-la-phaze-bobs-not-dead": {
  "date":"2027-02-05","time":"21:00","venueId":"l-orange-bleue-vitry-le-francois",
  "officialUrl":"https://bords2scenes.fr/agenda/la-tournee-du-coeur-3",
  "organizer":"Bords 2 Scènes",
  "proofType":"official-organizer-or-venue",
  "checkedFields":["artists","date","venue","genre","doorTime","concertStartTime"],
 },
}
VENUES = {
 "la-manufacture-saint-quentin": {
   "name":"La Manufacture","address":"8 rue Paul Codos",
   "postalCode":"02100","city":"Saint-Quentin","department":"02",
   "region":"Hauts-de-France","latitude":49.85444,"longitude":3.27029,
   "official":"https://www.saint-quentin.fr/1674-la-manufacture.htm",
   "geo":"https://tofromfrance.com/lieu/le-concert-des-deux-pianos-a-la-manufacture",
 },
 "l-orange-bleue-vitry-le-francois": {
   "name":"L'Orange Bleue","address":"4 rue Auguste Choisy",
   "postalCode":"51300","city":"Vitry-le-François","department":"51",
   "region":"Grand Est","latitude":48.72668,"longitude":4.57955,
   "official":"https://bords2scenes.fr/infos-pratiques/accueil-billetterie",
   "geo":"https://musitree.fr/concerts/salles/bords-2-scenes-lorange-bleue-vitry-le-francois/",
 },
}

def verify_event(row, ident):
    spec = SPECS[ident]
    expected = dict(
      id=ident,title="Cachemire + La Phaze + Bob's Not Dead",
      date=spec["date"],time=spec["time"],artistIds=BILL,
      venueId=spec["venueId"],genres=["Rock","Punk"],
      status="confirmed",officialUrl=spec["officialUrl"],
      sourceType="salle",organizer=spec["organizer"],
    )
    if (row.get("reviewDecision")!="approved"
        or row.get("reviewedBy")!="independent-official-verifier"
        or row.get("reviewedAt")!=DAY
        or row.get("event")!=expected or row.get("newArtists")!=[]):
        raise ValueError("Avis ou affiche modifiés")
    evidence=row.get("officialEvidence")
    if not isinstance(evidence,list) or len(evidence)!=2:
        raise ValueError("Deux preuves exigées")
    first,second=evidence
    if (first.get("url")!=spec["officialUrl"]
        or first.get("proofType")!=spec["proofType"]
        or first.get("checkedAt")!=DAY
        or first.get("checkedFields")!=spec["checkedFields"]
        or first.get("confirmedArtists")!=ARTISTS
        or first.get("concertStartTimeConfirmed")!=spec["time"]
        or second.get("url")!=TOUR
        or second.get("proofType")!="official-promoter-tour-calendar"
        or second.get("checkedAt")!=DAY
        or second.get("checkedFields")!=["date","city","venue"]):
        raise ValueError("Source, heure ou plateau non signés")
    return True

def verify_venue(row, ident):
    spec=VENUES[ident];v=row.get("venue") or {}
    if (row.get("reviewDecision")!="approved" or
        row.get("reviewedBy")!="independent-official-verifier" or
        row.get("reviewedAt")!=DAY or v.get("id")!=ident or
        any(v.get(key)!=spec[key] for key in
            ("name","address","postalCode","city","department","region","latitude","longitude")) or
        v.get("geoSource")!=spec["geo"] or
        "indicatif" not in v.get("geoPrecision","").lower()):
        raise ValueError("Salle, précision ou GPS non signé")
    sources=row.get("officialEvidence")
    if not isinstance(sources,list) or len(sources)!=2:
        raise ValueError("Sources salle manquantes")
    required=[
      (spec["official"],"official-venue-address",{"name","address","postalCode","city"}),
      (spec["geo"],"independent-named-venue-geolocation",{"venueName","coordinates"}),
    ]
    for proof,(url,kind,fields) in zip(sources,required):
        if (proof.get("url")!=url or proof.get("proofType")!=kind
            or proof.get("checkedAt")!=DAY
            or not fields.issubset(set(proof.get("checkedFields") or []))):
            raise ValueError("Source d'adresse ou GPS falsifiée")
    return True

class CoeurSaintQuentinVitrySigned(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.approvals={x["event"]["id"]:x for x in DOC["approvals"]}
        cls.venues={x["venue"]["id"]:x for x in DOC["venueApprovals"]}

    def test_unique_exact_approval_and_venue(self):
        self.assertEqual(len(cls_ids:=[x["event"]["id"] for x in DOC["approvals"]]),len(set(cls_ids)))
        self.assertEqual(len(DOC["venueApprovals"]),len(self.venues))
        for ident in SPECS:
            self.assertTrue(verify_event(self.approvals[ident],ident))
        for ident in VENUES:
            self.assertTrue(verify_venue(self.venues[ident],ident))

    def test_reject_mutations_of_events(self):
        for ident in SPECS:
            for name, mutate in [
             ("date",lambda r:r["event"].update(date="2027-12-31")),
             ("venue",lambda r:r["event"].update(venueId="fake-venue")),
             ("artist",lambda r:r["event"]["artistIds"].append("artiste-fantome")),
             ("time",lambda r:r["event"].update(time="22:00")),
             ("genre",lambda r:r["event"].update(genres=["Pop"])),
             ("url",lambda r:r["officialEvidence"][0].update(url="https://example.net")),
             ("lineup",lambda r:r["officialEvidence"][0].update(confirmedArtists=["Fake"])),
             ("tour",lambda r:r["officialEvidence"][1].update(url="https://fake.net")),
             ("stale",lambda r:r.update(reviewedAt="2026-01-01")),
             ("reviewer",lambda r:r.update(reviewedBy="automated-official-recheck")),
            ]:
                row=copy.deepcopy(self.approvals[ident]);mutate(row)
                with self.subTest(id=ident,mutation=name),self.assertRaises(ValueError):
                    verify_event(row,ident)

    def test_reject_mutations_of_venues(self):
        for ident in VENUES:
            for name,mutate in [
             ("lat",lambda r:r["venue"].update(latitude=0.0)),
             ("addr",lambda r:r["venue"].update(address="Adresse inconnue")),
             ("geo",lambda r:r["venue"].update(geoSource="https://fake.net")),
             ("source",lambda r:r["officialEvidence"][1].update(url="https://fake.net")),
            ]:
                row=copy.deepcopy(self.venues[ident]);mutate(row)
                with self.subTest(venue=ident,mutation=name),self.assertRaises(ValueError):
                    verify_venue(row,ident)

if __name__=="__main__":
    unittest.main()
