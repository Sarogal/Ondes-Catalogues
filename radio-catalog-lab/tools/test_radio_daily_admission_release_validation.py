import json
import unittest
from radio_daily_admission_release_validation import qualify_admission, validate_admission_release, typed_station_unique_player
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_publication_simulator import MemoryStore,publish,verify_visible
from radio_daily_v9_generator import digest,encode
from test_radio_daily_baseline_selection import signed
from test_radio_daily_v9_generator import fixture
from test_radio_daily_decision_preview import A, DAY, PAGE

URL="https://radio.example.org/live"


class StrictAdmissionTests(unittest.TestCase):
    def setUp(self):
        raw,d,e=fixture()
        doc=json.loads(raw)
        for row in doc["stations"]:
            row["logo"]=None
            row["editorial"].update(admission_state="approved",reviewed_at=DAY+"T00:00:00Z")
        self.signer=EphemeralLabSigner()
        self.pointer,self.raw=signed(doc,self.signer._key,self.signer.key_id)
        self.anchor=dict(expected_sha=digest(self.raw),expected_sequence=8,
            public_key=self.signer.public_key,key_id=self.signer.key_id)
        d["candidates"][0]["streamUrl"]=URL
        e["catalogBaselineSha256"]=digest(self.raw)
        row=e["records"][0]
        for field in ("lastSourceObservation","homepageEvidence","streamEvidence","continuityEvidence"):
            row[field]["streamSha256"]=digest(URL.encode())
        self.d,self.e=d,e
        self.args=dict(anchor=self.anchor,day=DAY,discovery=d,dossiers=e,
            search=self.search,fetch=self.fetch,probe=self.probe,continuity=self.continuity,hls=self.hls)

    def search(self,name):
        return [dict(stationuuid=A,name="Iron Radio",countrycode="GB",tags="metal",
            homepage=PAGE,url_resolved=URL,lastcheckok=1)]

    def fetch(self,url):
        return PAGE, ('<script type="application/ld+json">'+json.dumps(
            {"@type":"RadioStation","name":"Iron Radio","genre":"metal","streamUrl":URL})+'</script>').encode()

    def probe(self,url):
        return dict(streamSha256=digest(url.encode()),verdict="audio_sample_ok",frameChain="mp3")

    def continuity(self,url):
        return dict(verdict="continuous_icy_frame_indication",frameCodec="mp3")

    def hls(self,url):
        return dict(verdict="advancing_hls_audio_frame_indication",frameCodec="aac")

    def qualify(self,**kw):
        return qualify_admission(self.pointer,self.raw,**dict(self.args,**kw))

    def test_exact_verified_addition_preserves_existing_catalogue(self):
        body=self.qualify()
        new=json.loads(body); old=json.loads(self.raw)
        self.assertEqual(new["stations"][:-1],old["stations"])
        self.assertEqual(new["tombstones"],old["tombstones"])
        row=new["stations"][-1]
        self.assertEqual(row["legacy_aliases"],[A])
        self.assertEqual(row["streams"][0]["state"],"verified")
        self.assertIsNone(row["logo"])
        self.assertEqual(validate_admission_release(self.pointer,self.raw,body,**self.args),digest(body))

    def test_typed_station_without_stream_and_unique_player(self):
        node = {"@type":"RadioStation","name":"Iron Radio","genre":"metal"}
        body = ('<h1>Iron Radio</h1><audio src="'+URL+'"></audio>'
                '<script type="application/ld+json">'+json.dumps(node)+'</script>').encode()
        self.assertTrue(typed_station_unique_player("Iron Radio",PAGE,body,URL))
        self.assertEqual(json.loads(self.qualify(fetch=lambda u:(PAGE,body)))["stations"][-1]["display_name"],"Iron Radio")

    def test_typed_station_unique_player_refuses_ambiguity(self):
        node = {"@type":"RadioStation","name":"Iron Radio","genre":"metal"}
        other = dict(node,name="Other Radio")
        conflicting = dict(node,streamUrl="https://other.example.org/live")
        for identity, nodes, players in (
            ("Iron Radio",[node,other],[URL]),
            ("Iron Radio",[conflicting],[URL]),
            ("Iron Radio",[node],[URL,"https://other.example.org/live"]),
            ("Iron Radio network",[node],[URL]),
            ("Iron Radio",[],[URL]),
            ("Iron Radio",[node],[]),
        ):
            with self.subTest(identity=identity,nodes=nodes,players=players):
                body = ('<h1>'+identity+'</h1>'+
                        ''.join('<audio src="'+u+'"></audio>' for u in players)+
                        '<script type="application/ld+json">'+json.dumps(nodes)+'</script>').encode()
                self.assertFalse(typed_station_unique_player("Iron Radio",PAGE,body,URL))

    def test_missing_repeated_history_refused(self):
        self.e["records"][0]["continuityEvidence"]["positiveObservationDates"]=[DAY]
        with self.assertRaisesRegex(ValueError,"no qualified admission"):
            self.qualify()

    def test_directory_conflict_refused(self):
        with self.assertRaisesRegex(ValueError,"directory identity"):
            self.qualify(search=lambda n:self.search(n)+[dict(self.search(n)[0],stationuuid="cccccccc-cccc-4ccc-8ccc-cccccccccccc")])

    def test_missing_official_format_refused(self):
        with self.assertRaisesRegex(ValueError,"fresh station format"):
            self.qualify(fetch=lambda u:(PAGE,b"<html>Unrelated</html>"))

    def test_temporary_token_refused(self):
        url=URL+"?token=short"
        self.d["candidates"][0]["streamUrl"]=url
        for field in ("lastSourceObservation","homepageEvidence","streamEvidence","continuityEvidence"):
            self.e["records"][0][field]["streamSha256"]=digest(url.encode())
        with self.assertRaisesRegex(ValueError,"endpoint held"):
            self.qualify()

    def test_fresh_continuity_refused(self):
        with self.assertRaisesRegex(ValueError,"fresh direct continuity"):
            self.qualify(continuity=lambda u:dict(verdict="finite_response_review",frameCodec="mp3"))

    def test_hls_audio_not_manifest_only(self):
        def sample(u):
            return dict(streamSha256=digest(u.encode()),verdict="playlist_pending")
        self.assertEqual(json.loads(self.qualify(probe=sample))["stations"][-1]["streams"][0]["codec"],"aac")
        with self.assertRaisesRegex(ValueError,"fresh advancing HLS"):
            self.qualify(probe=sample,hls=lambda u:dict(verdict="advancing_hls_manifest_only"))

    def test_unrelated_mutation_refused(self):
        doc=json.loads(self.qualify())
        doc["stations"][0]["display_name"]="Injected"
        with self.assertRaisesRegex(ValueError,"unauthorized admission delta"):
            validate_admission_release(self.pointer,self.raw,encode(doc),**self.args)

    def test_simulated_publication(self):
        body=self.qualify()
        sha=validate_admission_release(self.pointer,self.raw,body,**self.args)
        store=MemoryStore(self.pointer,self.raw)
        result=publish(store,self.signer,self.pointer,self.raw,body,
            expected_sha=self.anchor["expected_sha"],expected_sequence=8,expected_candidate_sha=sha,day=DAY)
        self.assertEqual(result["sequence"],9)
        verify_visible(store,store.current(),sha=sha,sequence=9,signer=self.signer)


if __name__=="__main__":
    unittest.main()
