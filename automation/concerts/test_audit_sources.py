"""Tests de l'audit national : aucun accès réseau."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import audit_sources as audit

class VenueAuditTests(unittest.TestCase):
    def setUp(self):
        self.registry=json.loads((Path(__file__).resolve().parent/"venues-national.json").read_text(encoding="utf-8"))
        self.sources=json.loads((Path(__file__).resolve().parent/"sources.json").read_text(encoding="utf-8"))

    def test_119_ids_uniques_et_repartition_coherente(self):
        self.assertEqual(len(audit.load_registry(self.registry)),119)
        tampered=json.loads(json.dumps(self.registry))
        tampered["venues"].append(dict(tampered["venues"][0]))
        with self.assertRaises(ValueError):
            audit.load_registry(tampered)
        tampered=json.loads(json.dumps(self.registry))
        tampered["counts"]["official"]+=1
        with self.assertRaises(ValueError):
            audit.load_registry(tampered)

    def test_repartition_de_provenance(self):
        from collections import Counter
        self.assertEqual(Counter(v["sourceType"] for v in self.registry["venues"]),
                         Counter({"existing":43,"directory":33,"official":41,"institutional":2}))

    def test_annuaire_ne_deviens_jamais_agenda_officiel(self):
        x=next(v for v in self.registry["venues"] if v["sourceType"]=="directory" and not v.get("verifiedAgendaUrl"))
        row=audit.inspect(x,{})
        self.assertEqual(row["status"],"third_party_lead_only")
        self.assertFalse(row["monitoringProven"])
        self.assertFalse(row["publicationAllowed"])

    def test_salle_du_catalogue_source_manquante(self):
        x=next(v for v in self.registry["venues"] if v["sourceType"]=="existing"
               and not v.get("verifiedAgendaUrl"))
        row=audit.inspect(x,{})
        self.assertEqual(row["status"],"missing_official_agenda")

    def test_dix_neuf_agendas_identifies(self):
        found=[v for v in self.registry["venues"] if v.get("verifiedAgendaUrl")]
        self.assertEqual(len(found),19)
        self.assertTrue(all(v["verifiedAgendaUrl"].startswith("https://") for v in found))
        vauban=next(v for v in self.registry["venues"] if v["name"]=="Cabaret Vauban")
        self.assertFalse(vauban["enabled"])
        self.assertIn("live",vauban["agendaStatus"])
        self.assertFalse(any(v.get("publish_automatically") for v in self.sources["venues"]))

    def test_signaux_flux(self):
        parser=audit.Signals()
        parser.feed('<link rel="alternate" type="application/rss+xml" href="/rss"/>'
                    '<a href="/concerts/calendrier.ics">ICS</a>'
                    '<a href="/concert/test">Concert</a>')
        self.assertEqual(len(parser.rss),1)
        self.assertEqual(len(parser.ics),1)
        self.assertEqual(parser.events,1)

    def test_rapport_sans_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            result=audit.save(Path(folder),[{"id":"a","name":"S", "department":"34",
                                            "status":"third_party_lead_only"}])
            self.assertTrue(result["publishesNothing"])
            self.assertTrue((Path(folder)/"RAPPORT_AUDIT.md").is_file())
            self.assertEqual(result["count"],1)

if __name__=="__main__":
    unittest.main()
