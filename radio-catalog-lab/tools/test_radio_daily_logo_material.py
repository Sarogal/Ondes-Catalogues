import json
import unittest
from radio_daily_logo_material import recover
from radio_daily_logo_plan import plan,stage
from radio_daily_v9_generator import digest
from test_radio_daily_logo_plan import reports, DATA, OLD, BODY, URL, PAGE, SID, DAY

def run(update=False,fetch_page=None,fetch_image=None):
    raw,sha,m,n=reports(update)
    material,held=recover(raw,DAY,m,n,expected=sha,
        fetch_page=fetch_page or (lambda u:(PAGE,BODY)),
        fetch_image=fetch_image or (lambda u,h:(DATA,"image/png")))
    return raw,sha,m,n,material,held

class LogoMaterialTests(unittest.TestCase):
    def test_exact_object_recovered(self):
        raw,sha,m,n,material,held=run()
        self.assertFalse(held)
        self.assertEqual(material[SID]["imageBytes"],DATA)
        p,_=plan(raw,DAY,m,n,expected=sha)
        desc,path,data=stage(json.loads(raw)["stations"][0],p[0],material[SID])
        self.assertEqual(path,digest(DATA)+".png")
        self.assertEqual(desc["sha256"],digest(data))

    def test_changed_bytes_held(self):
        *_,material,held=run(fetch_image=lambda u,h:(OLD,"image/png"))
        self.assertFalse(material)
        self.assertEqual(held[0]["reason"],"artwork_object_unconfirmed")

    def test_changed_page_held_before_download(self):
        *_,material,held=run(fetch_page=lambda u:(PAGE,BODY+b" "),
                            fetch_image=lambda u,h:self.fail("unexpected download"))
        self.assertFalse(material)
        self.assertEqual(held[0]["reason"],"artwork_page_unconfirmed")

    def test_update_rechecks_station_declaration(self):
        *_,material,held=run(True,fetch_page=lambda u:(PAGE,b"<title>Iron Radio</title>"))
        self.assertFalse(material)
        self.assertEqual(held[0]["reason"],"artwork_page_unconfirmed")

    def test_wrong_mime_held(self):
        *_,material,held=run(fetch_image=lambda u,h:(DATA,"image/jpeg"))
        self.assertFalse(material)
        self.assertEqual(held[0]["reason"],"artwork_object_unconfirmed")

    def test_update_exact_object(self):
        *_,material,held=run(True)
        self.assertIn(SID,material)
        self.assertFalse(held)

if __name__=="__main__":
    unittest.main()
