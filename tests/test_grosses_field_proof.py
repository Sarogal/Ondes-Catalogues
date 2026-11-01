import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from grossesondes_field_proof import (
 normalize,words_present,cernunnos_update,fantasmagorik_update
)
from grossesondes_stage import stage
from test_grosses_stage import fixtures

ORIGINAL=["Adfeilion","Arthuan Rebis Trio","Domhain","Einherjer","Fejd",
 "Firemage","Maruna","Morgarten","Ondfødt","Rhesus","Saor","Svartsot",
 "Trold","Uttern","XIV Dark Centuries","Ydhessä"]
NEW=["Glyphe","Askemåne","Keltania","Ruadh","Fianna Bán","Waldkauz"]
PROPOSED=ORIGINAL+NEW
PRICE_PATCH=("Préventes 2027 : vendredi 45 € ; samedi 60 € ; dimanche 60 € ; "
 "pass 3 jours 130 €. Sur place (site officiel) : samedi ou dimanche 65 € ; "
 "pass 2 jours 100 € (catégorie à clarifier).")
GROUP_TEXT="Lineup #cernunnos2027 Part 1 "+ " ".join(ORIGINAL+NEW[:4])
HOME_TEXT=("CERNUNNOS PAGAN FEST VENDREDI 12 SAMEDI 13 DIMANCHE 14 "
           "FÉVRIER 2027 La Ferme du Buisson Noisiel")
INFO_TEXT=("QUAND Vendredi 12.02 Samedi 13.02 Dimanche 14 02 "
  "PRÉVENTES pass 1 JOUR Vendredi 45 € pass 1 JOUR Samedi OU Dimanche 60 € "
  "Pass 3 jours 12 13 14 Février 130 € SUR PLACE "
  "pass 1 jour samedi ou dimanche 65 € pass 2 jours 100 € "
  "La Ferme du Buisson Noisiel")
GOOD={"cernunnos_groups":GROUP_TEXT,"cernunnos_home":HOME_TEXT,
      "cernunnos_info":INFO_TEXT,
      "fantasmagorik_ticket":("Fantasmagorik Fest par Tout en Scène "
        "Pass Avant première à partir de 10€ La Poudrière "
        "330 Rue Roger Salengro 59495 Leffrinckoucke"),
      "fantasmagorik_date":("Fantasmagorik Fest 31 octobre 2026 "
        "La Poudrière Leffrinckoucke")
}

def cernunnos():
    original={"slug":"cernunnos-pagan-fest","name":"Cernunnos Pagan Fest",
        "lineup":ORIGINAL[:],"bands":16,"price":"ancien","notes":"ancienne annonce",
        "verificationStatus":"16 noms","sourceConfidence":"ancien",
        "auditSources":[],"lastVerified":"2026-10-10",
        "startDate":"2027-02-12","endDate":"2027-02-14",
        "status":"Confirmé"}
    changes=[]
    for key,new in (
        ("lineup",PROPOSED),("bands",22),("price",PRICE_PATCH),
        ("notes","texte de la veille qui prétend que 22 groupes sont affichés"),
        ("verificationStatus","22 noms"),
        ("sourceConfidence","organisateur + presse"),
        ("auditSources",["https://www.cernunnospaganfest.fr/groupes/"]),
        ("lastVerified","2026-10-29")
    ):
        changes.append({"field":key,"before":original[key],"after":new})
    return original,{"slug":original["slug"],"evidence":["https://www.cernunnospaganfest.fr/groupes/"],
                     "changes":changes}

def fantasy():
    original={"slug":"fantasmagorik-fest-2026","name":"Fantasmagorik Fest",
       "status":"Annoncé","lastVerified":"2026-10-22","verificationStatus":"2 groupes",
       "startDate":"2026-10-31","endDate":"2026-10-31"}
    changes=[{"field":k,"before":original[k],"after":v} for k,v in (
      ("status","Confirmé"),("lastVerified","2026-10-29"),
      ("verificationStatus","Billetterie et lieu corroborés")
    )]
    return original,{"slug":original["slug"],
      "evidence":["https://www.helloasso.com/associations/tout-en-scene/evenements/fantasmagorik-fest"],
      "changes":changes}

class FieldProofTests(unittest.TestCase):
    def test_character_transliteration(self):
        self.assertEqual(normalize("Ondfødt"),"ondfodt")
        self.assertEqual(normalize("Ydhessä"),"ydhessa")
        self.assertTrue(words_present("OND FODT et ASKEMÅNE",["askemane"]))
    def test_partial_lineup_keeps_unconfirmed_pending(self):
        orig,patch=cernunnos()
        validated=cernunnos_update(orig,patch,GOOD,"2026-10-29")
        self.assertIsNotNone(validated)
        result,fields,pending=validated
        self.assertEqual(result["bands"],20)
        self.assertEqual(result["lineup"],ORIGINAL+NEW[:4])
        self.assertEqual(pending,["Fianna Bán","Waldkauz"])
        self.assertEqual(orig["bands"],16)
        self.assertNotIn("billetterie ouverte",result["notes"])
        self.assertNotIn("22 groupes",result["notes"])
        self.assertIn("130 €",result["price"])
    def test_missing_date_year_rejects(self):
        orig,patch=cernunnos()
        bad=dict(GOOD,cernunnos_home=HOME_TEXT.replace("2027","2026"))
        self.assertIsNone(cernunnos_update(orig,patch,bad,"2026-10-29"))
    def test_missing_official_new_artist_holds_all_if_no_progress(self):
        orig,patch=cernunnos()
        bad=dict(GOOD,cernunnos_groups="Lineup #cernunnos2027 Part 1 "+" ".join(ORIGINAL))
        self.assertIsNone(cernunnos_update(orig,patch,bad,"2026-10-29"))
    def test_price_mismatch_rejects(self):
        orig,patch=cernunnos()
        bad=dict(GOOD,cernunnos_info=INFO_TEXT.replace("130 €","120 €"))
        self.assertIsNone(cernunnos_update(orig,patch,bad,"2026-10-29"))
    def test_addition_cannot_remove_original_group(self):
        orig,patch=cernunnos()
        patch["changes"][0]["after"]=ORIGINAL[:-1]+NEW
        self.assertIsNone(cernunnos_update(orig,patch,GOOD,"2026-10-29"))
    def test_price_patch_tampering_rejects(self):
        orig,patch=cernunnos()
        patch["changes"][2]["after"]="Tarif 3 jours 1€"
        self.assertIsNone(cernunnos_update(orig,patch,GOOD,"2026-10-29"))
    def test_fantasmagorik_organizer_and_local_date(self):
        orig,patch=fantasy()
        x=fantasmagorik_update(orig,patch,GOOD,"2026-10-29")
        self.assertIsNotNone(x)
        result,fields,_=x
        self.assertEqual(result["status"],"Confirmé")
        self.assertEqual(orig["status"],"Annoncé")
        self.assertEqual(result["lastVerified"],"2026-10-29")
    def test_fantasmagorik_date_wrong_blocks(self):
        orig,patch=fantasy()
        bad=dict(GOOD,fantasmagorik_date=GOOD["fantasmagorik_date"].replace("31 octobre 2026","31 octobre 2025"))
        self.assertIsNone(fantasmagorik_update(orig,patch,bad,"2026-10-29"))
    def test_fantasmagorik_venue_wrong_blocks(self):
        orig,patch=fantasy()
        bad=dict(GOOD,fantasmagorik_ticket=GOOD["fantasmagorik_ticket"].replace("La Poudrière","La Boîte"))
        self.assertIsNone(fantasmagorik_update(orig,patch,bad,"2026-10-29"))
    def test_stage_can_publish_two_independent_partial_updates(self):
        c,h,p=fixtures()
        old,update=cernunnos()
        old_f,update_f=fantasy()
        c["festivals"][3]=old
        c["festivals"][4]=old_f
        p["updates"]=[update,update_f]
        p["additions"]=[]
        out,report=stage(c,h,p,GOOD,"2026-10-29")
        self.assertEqual(len(report["accepted_updates"]),2)
        self.assertEqual(out["festivals"][3]["bands"],20)
        self.assertEqual(out["festivals"][4]["status"],"Confirmé")
        self.assertEqual(len(report["held"]),1)
        self.assertEqual(report["held"][0]["pending_names"],["Fianna Bán","Waldkauz"])
        self.assertEqual(c["festivals"][3]["bands"],16)
        self.assertEqual(len(h["knownFestivals"]),170)
    def test_without_source_update_is_held(self):
        c,h,p=fixtures()
        old,update=cernunnos()
        c["festivals"][3]=old
        p["updates"]=[update]
        p["additions"]=[]
        out,report=stage(c,h,p,{},"2026-10-29")
        self.assertEqual(len(report["accepted_updates"]),0)
        self.assertEqual(out["festivals"][3],old)
        self.assertEqual(len(report["held"]),1)


class SoldOutTicketTests(unittest.TestCase):
    def test_offline_ticket_certificate_is_integrity_pinned(self):
        from grossesondes_field_proof import verified_2026_11_01_ticket_snapshot
        observed=verified_2026_11_01_ticket_snapshot()
        self.assertIn("in your face 6",observed)
        self.assertEqual(observed.count("sold out"),3)
        self.assertIn("pass vendredi 27",observed)

    def test_three_categories_need_explicit_independent_sold_out_proof(self):
        from grossesondes_field_proof import in_your_face_sold_out, IN_YOUR_FACE_TICKET_URL
        old = {"slug":"in-your-face-6-2026", "source":IN_YOUR_FACE_TICKET_URL,
               "notes":"Festival annoncé.", "lastVerified":"2026-10-10"}
        patch = {"evidence":[IN_YOUR_FACE_TICKET_URL], "verified_at":"2026-11-01",
                 "changes":[
                     {"field":"notes", "before":old["notes"],
                      "after":old["notes"]+" | Billetterie officielle consultée le 01/11/2026 : trois pass épuisés."},
                     {"field":"lastVerified", "before":"2026-10-10", "after":"2026-11-01"}]}
        text = ("in your face 6 le zinor novembre 2026 "
                "pass 2 jours 42 sold out no seats available "
                "pass vendredi 27 sold out no seats available "
                "pass samedi 29 sold out no seats available")
        self.assertIsNotNone(in_your_face_sold_out(
            old,patch,{"in_your_face_ticket":text},"2026-11-01"))
        self.assertIsNone(in_your_face_sold_out(
            old,patch,{"in_your_face_ticket":text.replace("sold out","on sale",1)},"2026-11-01"))
        self.assertIsNone(in_your_face_sold_out(
            old,dict(patch,evidence=["https://example.org/"]),{"in_your_face_ticket":text},"2026-11-01"))

if __name__=="__main__":
    unittest.main()
