"""Unknown-origin HTTPS research: security and independent evidence boundary."""
from __future__ import annotations

import copy
import datetime as dt
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_evidence_probe as probe
import source_admission_intake as intake

TODAY = dt.date(2026, 11, 21)
DETAIL = "https://unknown-venue.fr/agenda/first-metal-show/"
LISTING = "https://unknown-venue.fr/agenda/"


def queue(host="unknown-venue.fr", *, date="2027-03-03", stable=2):
    source_page = "https://" + host + "/agenda/"
    event_url = source_page + "first-metal-show/"
    return {"host": host, "alreadyReviewedAuthority": False,
            "stableOnDistinctDays": stable, "sameHostEventLeads": 1,
            "eventLeads": 1, "examples": [{
                "sourcePage": source_page, "eventUrl": event_url,
                "date": date, "candidateId": "unknown-artist-metal"
            }]}


def report(rows):
    return {"schema": intake.SCHEMA,
            "publicationAllowed": False, "automaticTrustGranted": False,
            "reviewQueue": rows}


def html_event(date="2027-03-03", kind="MusicEvent", url=DETAIL):
    return ('<html><title>New bands</title>'
            '<script type="application/ld+json">'
            + json.dumps({"@type": kind, "name": "Unknown metal band",
                          "url": url, "startDate": date + "T20:00:00+01:00"})
            + '</script></html>')


class SourceProbeTests(unittest.TestCase):
    def test_unknown_domains_can_be_examined_without_a_manifest_entry(self):
        hits = []
        def fetch(url, cache):
            hits.append(url)
            return html_event() if url == DETAIL else "<html>Venue programme</html>"
        data = probe.build(report([queue()]), TODAY, slot=2, fetch=fetch)
        self.assertEqual(hits, [LISTING, DETAIL])
        self.assertEqual(data["eligibleUnknownHosts"], 1)
        self.assertEqual(data["checkedHosts"], 1)
        self.assertEqual(data["sourceChecks"][0]["status"],
                         "needs_independent_official_corroboration")
        self.assertTrue(data["sourceChecks"][0]["matchingStructuredDate"])
        self.assertFalse(data["automaticTrustGranted"])
        self.assertFalse(data["independentCorroborationVerified"])
        self.assertFalse(data["publicationAllowed"])

    def test_unknown_tour_organizer_calendar_gets_private_evidence(self):
        row = queue("unlisted-tour.fr", date="2027-02-04", stable=3)
        row["sameHostEventLeads"] = 7
        row["eventLeads"] = 7
        row["examples"][0].update({
            "sourcePage": "https://unlisted-tour.fr/",
            "eventUrl": "https://unlisted-tour.fr/",
            "city": "Saint-Jean-de-Védas (Montpellier)",
            "venue": "Victoire 2, 2 rue Théophraste-Renaudot",
        })
        document = (
            "<html><p>European touring metal 2027, 39 shows.</p><p>"
            "1/20 🇩🇪 Aschaffenburg – Colos-Saal<br/>"
            "2/3 🇫🇷 Grenoble – L’Ilyade<br/>"
            "2/4 🇫🇷 Montpellier – Victoire 2<br/>"
            "2/11 🇫🇷 Toulouse – Le Rex</p></html>")
        reads = []
        result = probe.build(
            report([row]), TODAY, slot=2,
            fetch=lambda url, cache: reads.append(url) or document)
        self.assertEqual(len(reads), 2)
        self.assertEqual(result["checkedHosts"], 1)
        check = result["sourceChecks"][0]
        self.assertTrue(check["matchingVisibleTourDatePlace"])
        self.assertFalse(check["matchingStructuredDate"])
        self.assertEqual(check["status"],
                         "needs_independent_official_corroboration")
        self.assertFalse(check["independentCorroborationVerified"])
        self.assertFalse(check["automaticTrustGranted"])
        self.assertFalse(check["publicationAllowed"])
        self.assertFalse(result["publicationAllowed"])
        # One show is not a reviewed multi-stop tour. No special-case domain.
        row["eventLeads"] = row["sameHostEventLeads"] = 1
        result = probe.build(
            report([row]), TODAY, slot=2,
            fetch=lambda url, cache: document)
        self.assertFalse(
            result["sourceChecks"][0]["matchingVisibleTourDatePlace"])
        self.assertEqual(result["sourceChecks"][0]["status"],
                         "needs_individual_event_evidence")

    def test_page_claim_cannot_grant_trust_or_event_approval(self):
        before = report([queue()])
        untouched = copy.deepcopy(before)
        def fetch(url, _):
            return html_event() if url == DETAIL else "<html>Fake concert agenda</html>"
        result = probe.build(before, TODAY, slot=2, fetch=fetch)
        self.assertEqual(before, untouched)
        self.assertFalse(result["sourceChecks"][0]["independentCorroborationVerified"])
        self.assertFalse(result["sourceChecks"][0]["publicationAllowed"])
        self.assertFalse(result["sourceChecks"][0]["automaticTrustGranted"])

    def test_wrong_date_fake_event_and_unstructured_page_cannot_qualify(self):
        for body in ("<html>New band 2027-03-03</html>",
                     html_event(date="2027-03-04"),
                     html_event(url="https://evil.example.org/show"),
                     html_event(kind="TheaterEvent")):
            with self.subTest(body=body[:100]):
                result = probe.build(report([queue()]), TODAY, slot=2,
                    fetch=lambda url, cache: (
                        body if url == DETAIL else "<html>Listing</html>"))
                self.assertEqual(
                    result["sourceChecks"][0]["status"],
                    "needs_individual_event_evidence")
                self.assertFalse(result["sourceChecks"][0]["matchingStructuredDate"])

    def test_fail_closed_on_network_and_robots_errors(self):
        for error in (ValueError("robots.txt"), OSError("dns failure"),
                      TimeoutError("timeout")):
            def broken(url, cache):
                raise error
            result = probe.build(report([queue()]), TODAY, slot=2, fetch=broken)
            self.assertEqual(result["sourceChecks"][0]["status"],
                             "held_unverifiable_source")
            self.assertFalse(result["sourceChecks"][0]["firstPartyPageFetched"])
            self.assertFalse(result["automaticTrustGranted"])

    def test_reviewed_hosts_and_offsite_only_sources_cannot_be_scanned(self):
        trusted = queue("slhproductions.fr")
        trusted["alreadyReviewedAuthority"] = True
        offsite = queue("unknown-bar.fr")
        offsite["sameHostEventLeads"] = 0
        first_day = queue("new-once.fr", stable=0)
        def should_not_fetch(*args):
            raise AssertionError("No network for inadmissible source")
        result = probe.build(
            report([trusted, offsite, first_day]), TODAY,
            slot=0, fetch=should_not_fetch)
        self.assertEqual(result["eligibleUnknownHosts"], 0)
        self.assertEqual(result["sourceChecks"], [])

    def test_scans_rotate_across_many_unregistered_domains(self):
        rows = [queue(f"unknown-{i:03d}.fr") for i in range(215)]
        scanned = set()
        for day in range(24):
            for slot in (0, 1, 2):
                selected = probe.choose(
                    rows, TODAY + dt.timedelta(days=day), slot, 3)
                self.assertLessEqual(len(selected), 3)
                scanned.update(row["host"] for row in selected)
        self.assertEqual(len(scanned), 215)

    def test_untrusted_origin_validation(self):
        for url in (
            "http://newbar.fr/show",
            "https://localhost/show",
            "https://127.0.0.1/show",
            "https://private.local/show",
            "https://name:pwd@newbar.fr/show",
            "https://newbar.fr:8080/show",
            "https://newbar.fr/show#fragment",
            "https://newbar.fr.evil.example/show",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                probe.checked_uri(url, "newbar.fr")
        self.assertEqual(probe.checked_uri("https://newbar.fr/show/?q=x",
                                            "newbar.fr"), "/show/?q=x")

    def test_dns_rejects_mixed_private_and_public_results(self):
        def entry(ip):
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                    (ip, 443))
        for ips in (
            ["8.8.8.8", "127.0.0.1"],
            ["8.8.8.8", "10.0.0.1"],
            ["8.8.8.8", "::1"],
            ["192.168.0.4"],
            [],
        ):
            with self.subTest(ips=ips), patch.object(
                probe.socket, "getaddrinfo", return_value=[entry(ip) for ip in ips]
            ), self.assertRaises(ValueError):
                probe.public_ip_addresses("newbar.fr")
        with patch.object(probe.socket, "getaddrinfo",
                          return_value=[entry("8.8.8.8")]):
            self.assertEqual(probe.public_ip_addresses("newbar.fr"), ["8.8.8.8"])

    def test_safe_fetch_keeps_pinned_ip_and_robots_policy(self):
        calls = []
        def fake_request(url, host, ip, cap=probe.MAX_BYTES):
            calls.append((url,host,ip))
            if url.endswith("/robots.txt"):
                return 200, "User-agent: *\nDisallow: /hidden/\nAllow: /agenda/\n"
            return 200, "<html>Event</html>"
        with patch.object(probe, "public_ip_addresses", return_value=["8.8.8.8"]), \
             patch.object(probe, "request_pinned", side_effect=fake_request):
            cache = {}
            self.assertEqual(probe.safe_fetch("https://newbar.fr/agenda/", cache),
                             "<html>Event</html>")
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(ip == "8.8.8.8" for _, _, ip in calls))
            with self.assertRaisesRegex(ValueError, "robots.txt"):
                probe.safe_fetch("https://newbar.fr/hidden/secret/", cache)
            self.assertEqual(len(calls), 2)

    def test_redirects_are_not_followed_even_on_same_host(self):
        class FakeResponse:
            status = 302
            def read(self, cap):
                return b""
        class FakeConnection:
            def __init__(self, *a, **kw):
                pass
            def request(self, *a, **kw):
                pass
            def getresponse(self):
                return FakeResponse()
            def close(self):
                pass
        with patch.object(probe, "PinnedHTTPS", FakeConnection):
            with self.assertRaisesRegex(ValueError, "non-success"):
                probe.request_pinned("https://newbar.fr/event/", "newbar.fr",
                                     "8.8.8.8")

    def test_invalid_queue_fails_closed(self):
        for invalid in (
            {}, {"schema": intake.SCHEMA, "reviewQueue": []},
            {**report([]), "publicationAllowed": True},
            {**report([]), "automaticTrustGranted": True},
        ):
            with self.assertRaises(ValueError):
                probe.build(invalid, TODAY)


if __name__ == "__main__":
    unittest.main()
