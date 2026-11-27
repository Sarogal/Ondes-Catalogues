import copy
import json
import unittest
from radio_daily_repair_material import recover
from radio_daily_repair_plan import plan
from radio_daily_maintenance_preview import digest
from test_radio_daily_repair_plan import fixture, SID, UID, NEW, PAGE

def row(url=NEW):
    return {"stationuuid":UID,"name":"Iron Radio","countrycode":"FR","homepage":PAGE,"url_resolved":url,"lastcheckok":1}

def page(url=NEW):
    return PAGE,('<script type="application/ld+json">'+json.dumps({"@type":"RadioStation","name":"Iron Radio","streamUrl":url})+'</script>').encode()

def run(url=NEW,search=None,fetch=None,strong=True):
    raw,sha,m,r,c=fixture(new=url,strong=strong)
    p=plan(raw,m,r,c,expected=sha)
    return recover(raw,m,r,c,p,expected=sha,search=search or (lambda n:[row(url)]),fetch=fetch or (lambda u:page(url)))

class MaterialTests(unittest.TestCase):
    def test_exact_url_rehydrated(self):
        urls,held=run()
        self.assertEqual(urls,{(SID,digest(NEW)):NEW})
        self.assertEqual(held,[])

    def test_changed_directory_fingerprint(self):
        urls,held=run(search=lambda n:[row(NEW+"2")])
        self.assertFalse(urls)
        self.assertEqual(held[0]["reason"],"replacement_fingerprint_not_found")
        self.assertNotIn(NEW,json.dumps(held))

    def test_broadcaster_link_lost(self):
        urls,held=run(fetch=lambda u:page(NEW+"2"))
        self.assertFalse(urls)
        self.assertEqual(held[0]["reason"],"broadcaster_material_unconfirmed")

    def test_query_secret_not_returned(self):
        urls,held=run(url=NEW+"?token=secret")
        self.assertFalse(urls)
        self.assertEqual(held[0]["reason"],"unsafe_replacement_material")
        self.assertNotIn("secret",json.dumps(held))

    def test_no_proposal_no_network(self):
        urls,held=run(strong=False,search=lambda n:self.fail("unexpected network"))
        self.assertEqual((urls,held),({},[]))

    def test_forged_plan_refused_before_network(self):
        raw,sha,m,r,c=fixture()
        p=plan(raw,m,r,c,expected=sha)
        p["approvedCount"]=1
        with self.assertRaises(ValueError):
            recover(raw,m,r,c,p,expected=sha,search=lambda n:self.fail("unexpected network"))

    def test_incomplete_directory_response_held(self):
        urls,held=run(search=lambda n:[row()]*50)
        self.assertFalse(urls)
        self.assertEqual(held[0]["reason"],"directory_material_held")

if __name__=="__main__":
    unittest.main()
