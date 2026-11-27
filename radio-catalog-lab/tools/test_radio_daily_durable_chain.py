"""End-to-end synthetic daily chain; no real release, network, or key."""
import json
import unittest
from radio_daily_publication_simulator import publish, verify_visible
from radio_daily_v9_generator import encode, digest
from test_radio_daily_baseline_selection import signed
from test_radio_daily_logo_plan import DATA, OLD, URL, reports, DAY


class DurableDailyChainTests(unittest.TestCase):
    """Exercise the actual generator, signer, pointer and snapshot together.

    All observations are synthetic; no production key, network or remote store.
    The bootstrap fixture is already approved, not a promotion of TEST v8.
    """

    def test_two_daily_successors_restart_transfer_deploy_migrate_and_no_change(self):
        import tempfile
        from radio_daily_logo_release_validation import publish_logo_release
        from pathlib import Path
        from radio_daily_state_snapshot import transition_remote, POINTER, BODY
        from radio_daily_github_readback import GitHubReadback
        from unittest.mock import Mock, patch
        from radio_daily_release_context import STATE_FILES, REQUALIFY
        from radio_daily_unified_generator import build
        from radio_daily_decision_preview import decide
        from radio_daily_maintenance_preview import build as maintenance
        from radio_daily_repair_preview import build as repair
        from radio_daily_repair_confirmation import build as confirm
        from radio_daily_repair_plan import plan
        from radio_daily_status_preview import build as status
        from radio_daily_logo_maintenance import build as logo, official_source
        from radio_daily_missing_logo import build as missing
        from test_radio_daily_logo_plan import material, DAY1

        import secrets
        import subprocess
        from radio_daily_durable_lab_signer import DurableLabSigner
        from radio_daily_durable_lab_store import DurableLabStore
        from radio_daily_git_lab_transport import LocalGitLabTransport, ZERO, REF
        from radio_daily_git_lab_transfer import transmit
        from radio_daily_git_lab_reader import prepare_from_git
        from radio_daily_deployment_verify import verify_deployment, PublicResponse, ROOT, POINTER_URL
        from radio_daily_baseline_verify import strict_json
        from radio_daily_publication_simulator import inventory
        raw, *_ = reports()
        doc = json.loads(raw)
        doc["stations"][0]["editorial"].update(
            admission_state="approved", reviewed_at=DAY1+"T00:00:00Z")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            password = secrets.token_bytes(32)
            key_file = root/"lab-key.pem"
            signer = DurableLabSigner.create(key_file, password)
            pin = dict(expected_public_key=signer.public_key, expected_key_id=signer.key_id)
            key = dict(public_key=signer.public_key, key_id=signer.key_id)
            pointer, raw = signed(doc, signer._key, signer.key_id)
            bootstrap_sha = digest(raw)
            db = root/"lab.sqlite"
            store = DurableLabStore.initialize(db, pointer, raw, **key)
            def repo(name):
                path = root/name
                subprocess.run(["git", "init", "--bare", "--object-format=sha1", str(path)],
                               check=True, capture_output=True)
                return LocalGitLabTransport(path)
            source, receiver = repo("source.git"), repo("receiver.git")
            def transfer(seq, sha, lease):
                head = source.publish(store, expected_head=lease, expected_sequence=seq,
                                      expected_sha=sha)["commit"]
                args = dict(expected_commit=head, expected_remote_head=lease,
                            expected_sequence=seq, expected_sha=sha)
                result = transmit(source, receiver, store, **args)
                self.assertFalse(result["publicationAllowed"])
                self.assertTrue(transmit(source, receiver, store, **args)["resumed"])
                return head
            head = transfer(8, bootstrap_sha, ZERO)
            snapshot = root/"v8"
            snapshot.mkdir()
            (snapshot/POINTER).write_bytes(pointer)
            (snapshot/BODY).write_bytes(raw)
            for seq, days, image in ((8, (DAY1, DAY), DATA),
                                     (9, ("2026-11-27", "2026-11-28"), OLD)):
                raw = (snapshot/BODY).read_bytes()
                pointer = (snapshot/POINTER).read_bytes()
                sha = digest(raw)
                state = {k: json.loads((snapshot/name).read_bytes())
                         for k, name in STATE_FILES.items()
                         if (snapshot/name).exists()}
                observed_urls = []
                def fetch_image(url, host):
                    observed_urls.append(url)
                    return image, "image/png"
                for day in days:
                    discovery = dict(schemaVersion=1, scanDate=day,
                                     publicationAllowed=False, candidates=[])
                    dossiers = dict(schemaVersion=1, scanDate=day,
                                    publicationAllowed=False, approvedCount=0,
                                    catalogBaselineSha256=sha, records=[])
                    m = maintenance(raw, day, expected=sha, prior=state.get("maintenance"))
                    r = repair(raw, m, discovery, expected=sha, prior=state.get("repair"))
                    c = confirm(raw, r, expected=sha, prior=state.get("confirmation"))
                    rp = plan(raw, m, r, c, expected=sha)
                    st = status(raw, m, rp, expected=sha)
                    lm = logo(raw, day, expected=sha, prior=state.get("logo"),
                              limit=8, fetch=fetch_image)
                    nm = missing(raw, day, expected=sha, prior=state.get("missing"),
                                 limit=4, fetch_page=lambda u: (material()["pageUrl"],
                                                               material()["pageBytes"]),
                                 fetch_image=fetch_image)
                    state = dict(maintenance=m, repair=r, confirmation=c,
                                 status=st, logo=lm, missing=nm)
                self.assertEqual(observed_urls, [URL, URL])
                args = (raw, discovery, dossiers, decide(discovery, dossiers, sha),
                        m, r, c, rp, st, lm, nm)
                artwork = {doc["stations"][0]["go_station_id"]:
                           dict(material(), imageBytes=image)}
                objects = {}
                candidate, report = build(*args, expected=sha, expected_sequence=seq,
                                          artwork=artwork, object_output=objects)
                self.assertEqual(report["candidateSequence"], seq+1)
                self.assertEqual(len(report["logoChanges"]), 1)
                self.assertEqual(objects, {digest(image)+".png": image})
                # Replay evidence rather than trust the generator's summary.
                replay = {}
                rebuilt, _ = build(*args, expected=sha, expected_sequence=seq,
                                   artwork=artwork, object_output=replay)
                self.assertEqual((candidate, objects), (rebuilt, replay))
                args_publish = dict(expected_sha=sha, expected_sequence=seq,
                                    expected_candidate_sha=digest(candidate),
                                    day=day, objects=objects, logo_maintenance=lm,
                                    missing_logo=nm, artwork=artwork)
                stop = "before_pointer_swap" if seq == 8 else "after_pointer_swap"
                def interrupt(phase):
                    if phase == stop:
                        raise RuntimeError("laboratory interruption")
                with self.assertRaisesRegex(RuntimeError, "laboratory interruption"):
                    publish_logo_release(store, signer, pointer, raw, candidate,
                                         checkpoint=interrupt, **args_publish)
                if seq == 8:
                    self.assertEqual(store.current(), pointer)
                else:
                    self.assertNotEqual(store.current(), pointer)
                signer = DurableLabSigner.reopen(key_file, password, **pin)
                store = DurableLabStore(db, **key)
                result = publish_logo_release(store, signer, pointer, raw, candidate, **args_publish)
                self.assertEqual(result["resumed"], seq == 9)
                visible = store.current()
                self.assertEqual(verify_visible(store, visible, sha=digest(candidate),
                                 sequence=seq+1, signer=signer), json.loads(candidate))
                head = transfer(seq+1, digest(candidate), head)
                # Read the receiving repository, not the local publisher store.
                urls = {ROOT+strict_json(visible)["content_path"]:
                        (strict_json(visible)["content_path"], "application/json"),
                        POINTER_URL: ("pointer.json", "application/json")}
                for descriptor, name in inventory(strict_json(candidate)):
                    self.assertIsNotNone(name)
                    urls[descriptor["url"]] = ("objects/sha256/"+name, descriptor["mime_type"])
                def fetch(url, limit):
                    path, mime = urls[url]
                    data = receiver._git("show", head+":"+path)
                    self.assertLessEqual(len(data), limit)
                    return PublicResponse(200, url, mime, data)
                verify_args = dict(expected_commit=head, deployment_commit=head,
                    bootstrap_sha=bootstrap_sha, expected_sha=sha,
                    expected_sequence=seq, **key)
                with self.assertRaisesRegex(ValueError, "deployment"):
                    verify_deployment(receiver, deployment_status="pending", fetch=fetch, **verify_args)
                accepted = verify_deployment(receiver, deployment_status="success", fetch=fetch, **verify_args)
                self.assertTrue(accepted["deploymentVerified"])
                self.assertTrue(accepted["simulated"])
                git_raw, _, _, git_context = prepare_from_git(receiver, day=day, state=state,
                    expected_commit=head, bootstrap_sha=bootstrap_sha, expected_sha=sha,
                    expected_sequence=seq, **key)
                self.assertEqual(git_raw, candidate)
                self.assertEqual(git_context["selectedSequence"], seq+1)
                for k, name in STATE_FILES.items():
                    (snapshot/name).write_bytes(encode(state[k]))
                (snapshot/REQUALIFY[0]).write_bytes(encode(dossiers))
                before = {p.name: p.read_bytes() for p in snapshot.iterdir()}
                target = root/("v"+str(seq+1))
                # Exercise the remote acceptance adapter against the actual
                # receiving Git tree, with synthetic HTTPS/deployment responses.
                reader = GitHubReadback(lambda *args: None)
                reader.read_head = Mock(side_effect=lambda *args: receiver.head())
                def read_tree(destination, commit):
                    self.assertEqual(commit, head)
                    names = receiver._git("ls-tree", "-r", "--name-only", commit).decode().splitlines()
                    return {name: receiver._git("show", commit+":"+name) for name in names}
                reader.read_tree = Mock(side_effect=read_tree)
                remote_args = dict(reader=reader, deployment_id=42+seq,
                    environment="radio-lab-publisher-rehearsal", expected_commit=head,
                    bootstrap_sha=bootstrap_sha, day=day,
                    anchor=dict(expected_sha=sha, expected_sequence=seq, **key))
                with patch("radio_daily_remote_acceptance.PublicHTTPSReader",
                           side_effect=[Mock(), fetch]), \
                     patch("radio_daily_remote_acceptance.deployment_status",
                           side_effect=ValueError("deployment pending")):
                    with self.assertRaisesRegex(ValueError, "deployment pending"):
                        transition_remote(snapshot, target, **remote_args)
                self.assertFalse(target.exists())
                self.assertEqual(before, {p.name: p.read_bytes() for p in snapshot.iterdir()})
                with patch("radio_daily_remote_acceptance.PublicHTTPSReader",
                           side_effect=[Mock(), fetch]), \
                     patch("radio_daily_remote_acceptance.deployment_status",
                           return_value={"deploymentId":42+seq}):
                    ctx = transition_remote(snapshot, target, **remote_args)
                self.assertEqual(ctx["gitCommit"], head)
                self.assertEqual(ctx["deploymentId"], 42+seq)
                self.assertTrue(ctx["remoteReadbackVerified"])
                self.assertTrue(ctx["deploymentVerified"])
                self.assertEqual(json.loads((target/"release-context.json").read_bytes()), ctx)
                self.assertEqual(ctx["selectedSequence"], seq+1)
                self.assertEqual((target/BODY).read_bytes(), candidate)
                self.assertFalse((target/REQUALIFY[0]).exists())
                self.assertEqual(before, {p.name: p.read_bytes() for p in snapshot.iterdir()})
                snapshot = target
                self.assertEqual(official_source(json.loads(candidate)["stations"][0]), URL)
                self.assertEqual(receiver._git("rev-list", "--count", REF), str(seq-6).encode()+b"\n")

            # A fresh collection of the now-current image must not create v11.
            raw = (snapshot/BODY).read_bytes()
            pointer = (snapshot/POINTER).read_bytes()
            sha = digest(raw)
            day = "2026-11-29"
            state = {k: json.loads((snapshot/name).read_bytes()) for k, name in STATE_FILES.items()}
            d = dict(schemaVersion=1, scanDate=day, publicationAllowed=False, candidates=[])
            e = dict(schemaVersion=1, scanDate=day, publicationAllowed=False,
                     approvedCount=0, catalogBaselineSha256=sha, records=[])
            m = maintenance(raw, day, expected=sha, prior=state["maintenance"])
            r = repair(raw, m, d, expected=sha, prior=state["repair"])
            c = confirm(raw, r, expected=sha, prior=state["confirmation"])
            rp = plan(raw, m, r, c, expected=sha)
            lm = logo(raw, day, expected=sha, prior=state["logo"], limit=8,
                      fetch=lambda u, h: (OLD, "image/png"))
            nm = missing(raw, day, expected=sha, prior=state["missing"])
            candidate, report = build(raw, d, e, decide(d, e, sha), m, r, c, rp,
                                      status(raw, m, rp, expected=sha), lm, nm,
                                      expected=sha, expected_sequence=10)
            self.assertIsNone(candidate)
            self.assertFalse(report["changed"])
            result = publish(store, signer, pointer, raw, candidate,
                             expected_sha=sha, expected_sequence=10,
                             expected_candidate_sha=None, day=day)
            self.assertFalse(result["changed"])
            self.assertEqual(store.current(), pointer)
            self.assertEqual(source.head(), head)
            self.assertEqual(receiver.head(), head)
            self.assertEqual(receiver._git("rev-list", "--count", REF), b"3\n")
