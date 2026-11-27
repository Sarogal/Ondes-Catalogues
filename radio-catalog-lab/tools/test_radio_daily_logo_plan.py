import copy
import hashlib
import io
import json
import unittest
from PIL import Image
from radio_daily_logo_plan import plan, stage, PREVIEW_BASE
from radio_daily_v9_generator import encode,digest
from radio_daily_logo_maintenance import build as maintain
from radio_daily_missing_logo import build as missing
from test_radio_daily_repair_plan import fixture, PAGE, SID

DAY1="2026-11-25"
DAY="2026-11-26"
URL="https://radio.example.org/logo.png"
BODY=('<script type="application/ld+json">'+json.dumps({"@type":"RadioStation","name":"Iron Radio","logo":URL})+'</script>').encode()

def png(color):
    f=io.BytesIO()
    Image.new("RGB",(128,128),color).save(f,format="PNG")
    return f.getvalue()

DATA=png("red")
OLD=png("blue")

def reports(update=False):
    raw,*_=fixture()
    doc=json.loads(raw)
    s=doc["stations"][0]
    if update:
        sha=digest(OLD)
        s["logo"].update(asset_id="sha256:"+sha,sha256=sha,byte_size=len(OLD),width=128,height=128,url=URL)
    else:
        s["logo"]=None
    raw=encode(doc)
    sha=digest(raw)
    m=n=None
    for day in (DAY1,DAY):
        m=maintain(raw,day,expected=sha,prior=m,limit=8,fetch=lambda u,h:(DATA,"image/png"))
        n=missing(raw,day,expected=sha,prior=n,limit=4,fetch_page=lambda u:(PAGE,BODY),
                  fetch_image=lambda u,h:(DATA,"image/png"))
    return raw,sha,m,n

def material():
    return {"pageUrl":PAGE,"pageBytes":BODY,"sourceUrl":URL,"imageBytes":DATA}

class LogoPlanTests(unittest.TestCase):
    def test_attach_verified_object(self):
        raw,sha,m,n=reports()
        p,d=plan(raw,DAY,m,n,expected=sha)
        self.assertEqual(len(p),1)
        self.assertFalse(d)
        desc,path,data=stage(json.loads(raw)["stations"][0],p[0],material())
        self.assertEqual(desc["revision"],1)
        self.assertEqual(desc["url"],PREVIEW_BASE+path)
        self.assertEqual(desc["sha256"],digest(DATA))
        self.assertEqual(data,DATA)

    def test_update_requires_station_bound_declaration(self):
        raw,sha,m,n=reports(True)
        p,d=plan(raw,DAY,m,n,expected=sha)
        self.assertEqual(p[0]["operation"],"update_logo")
        s=json.loads(raw)["stations"][0]
        with self.assertRaises(ValueError):
            stage(s,p[0],dict(material(),pageBytes=b"<title>Iron Radio</title>"))
        desc,_,_=stage(s,p[0],material())
        self.assertEqual(desc["revision"],2)
        self.assertNotEqual(desc["sha256"],s["logo"]["sha256"])

    def test_reject_changed_object(self):
        raw,sha,m,n=reports()
        p,_=plan(raw,DAY,m,n,expected=sha)
        with self.assertRaises(ValueError):
            stage(json.loads(raw)["stations"][0],p[0],dict(material(),imageBytes=OLD))

    def test_reject_forged_derived_report(self):
        raw,sha,m,n=reports()
        n=copy.deepcopy(n)
        n["records"][0]["logoApproved"]=True
        with self.assertRaises(ValueError):
            plan(raw,DAY,m,n,expected=sha)

    def test_no_proposal_after_one_day(self):
        raw,sha,m,n=reports()
        m=maintain(raw,DAY,expected=sha)
        n=missing(raw,DAY,expected=sha,limit=4,fetch_page=lambda u:(PAGE,BODY),
                  fetch_image=lambda u,h:(DATA,"image/png"))
        p,_=plan(raw,DAY,m,n,expected=sha)
        self.assertEqual(p,[])

    def test_visible_logo_requires_named_registered_player_at_staging(self):
        raw,sha,m,n=reports()
        station=json.loads(raw)["stations"][0]
        stream=station["streams"][0]["url"]
        body=('<title>Iron Radio</title><img alt="Iron Radio logo" src="'+URL+'">'
              +'<audio src="'+stream+'"></audio>').encode()
        n=None
        for day in (DAY1,DAY):
            n=missing(raw,day,expected=sha,prior=n,limit=4,
                fetch_page=lambda u:(PAGE,body),fetch_image=lambda u,h:(DATA,"image/png"))
        p,_=plan(raw,DAY,m,n,expected=sha)
        self.assertEqual(len(p),1)
        desc,_,_=stage(station,p[0],dict(material(),pageBytes=body))
        self.assertEqual(desc["sha256"],digest(DATA))
        with self.assertRaises(ValueError):
            stage(station,p[0],dict(material(),pageBytes=body.replace(stream.encode(),b"https://other.example.org/live")))

if __name__=="__main__":
    unittest.main()
