import hashlib
import json
import unittest
from radio_daily_repair_preview import build
from radio_daily_maintenance_preview import build as maintenance,digest

DAY="2026-11-26"
UID="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
NEW="cccccccc-cccc-4ccc-8ccc-cccccccccccc"
OLD="https://radio.example.org/old"
NEXT="https://stream.example.org/new?token=secret"
PAGE="https://radio.example.org/metal"
SID="go-station-1"

def fixture():
    s={"go_station_id":SID,"display_name":"Iron Radio","country_code":"FR","homepage":PAGE,
       "status":{"state":"active"},"streams":[{"stream_id":"s1","url":OLD,"previous_urls":["https://radio.example.org/former"]}],
       "radio_browser_uuids":[{"uuid":UID,"state":"current"}],"legacy_aliases":[UID]}
    raw=json.dumps({"schema_version":1,"release_sequence":8,"stations":[s],"tombstones":[]}).encode()
    sha=hashlib.sha256(raw).hexdigest()
    m=maintenance(raw,DAY,expected=sha,limit=1,probe=lambda u:{"streamSha256":digest(u),"verdict":"needs_review","reason":"http_not_successful"})
    d={"schemaVersion":1,"publicationAllowed":False,"scanDate":DAY,"candidates":[]}
    return raw,sha,m,d

def candidate(**kw):
    return dict({"stationuuid":UID,"name":"Iron Radio","homepage":PAGE,"countrycode":"FR",
                 "url_resolved":NEXT,"lastcheckok":1},**kw)

def run(rows=None,prior=None):
    raw,sha,m,d=fixture()
    return build(raw,m,d,expected=sha,prior=prior,limit=1,search=lambda name:rows or [])

class RepairTests(unittest.TestCase):
    def test_exact_identity_and_digest_only(self):
        r=run([candidate()])
        self.assertEqual(r["stationsWithFreshHints"],1)
        h=r["records"][0]["hints"][0]
        self.assertEqual(h["streamSha256"],digest(NEXT))
        self.assertEqual(h["identityHint"],"known_uuid_and_exact_identity")
        self.assertFalse(h["technicalVerified"])
        self.assertNotIn("secret",json.dumps(r))
        self.assertFalse(r["publicationAllowed"])

    def test_same_name_different_page_country_or_old_url_held(self):
        r=run([candidate(homepage="https://radio.example.org/other"),candidate(countrycode="GB"),
               candidate(url_resolved=OLD),candidate(url_resolved="https://radio.example.org/former"),
               candidate(url_resolved="http://127.0.0.1/audio"),candidate(name="Other Radio")])
        self.assertEqual(r["stationsWithFreshHints"],0)

    def test_unknown_uuid_exact_identity_only_hypothesis(self):
        h=run([candidate(stationuuid=NEW)])["records"][0]["hints"][0]
        self.assertEqual(h["identityHint"],"new_uuid_exact_identity")
        self.assertFalse(h["broadcasterVerified"])

    def test_same_day_and_healthy_not_queried(self):
        r=run([candidate()])
        raw,sha,m,d=fixture()
        self.assertEqual(build(raw,m,d,expected=sha,prior=r,limit=1,search=lambda n:self.fail("same day"))["attemptedCount"],0)
        m["records"][0]["reviewStatus"]="audio_sample_observed"
        self.assertEqual(build(raw,m,d,expected=sha,limit=1,search=lambda n:self.fail("healthy"))["eligibleStationCount"],0)

    def test_failed_search_preserves_old_hints_and_date(self):
        r=run([candidate()])
        raw,sha,m,d=fixture()
        m["scanDate"]=d["scanDate"]="2026-11-27"
        def fail(name):raise OSError("unavailable")
        result=build(raw,m,d,expected=sha,prior=r,limit=1,search=fail)
        row=result["records"][0]
        self.assertEqual(row["searchStatus"],"service_held")
        self.assertEqual(row["hintsObservedDate"],DAY)
        self.assertEqual(row["hints"],r["records"][0]["hints"])

    def test_full_page_is_incomplete(self):
        r=run([candidate() for _ in range(50)])
        self.assertEqual(r["records"][0]["searchStatus"],"incomplete_search")

    def test_other_catalogue_owner_held(self):
        raw,sha,m,d=fixture()
        doc=json.loads(raw)
        import copy
        s=copy.deepcopy(doc["stations"][0])
        s["go_station_id"]="go-station-2"
        s["radio_browser_uuids"]=[{"uuid":OTHER,"state":"current"}]
        s["legacy_aliases"]=[OTHER]
        doc["stations"].append(s)
        raw=json.dumps(doc).encode()
        sha=hashlib.sha256(raw).hexdigest()
        m=maintenance(raw,DAY,expected=sha,limit=2,probe=lambda u:{"streamSha256":digest(u),"verdict":"needs_review","reason":"http_not_successful"})
        r=build(raw,m,d,expected=sha,limit=1,search=lambda n:[candidate(stationuuid=OTHER)])
        self.assertEqual(r["stationsWithFreshHints"],0)

if __name__=="__main__":
    unittest.main()
