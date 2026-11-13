"""Offline regression tests for a fail-closed patch of the actual Concerts site files."""
import tempfile
import unittest
from pathlib import Path

from scripts.concerts_site_status_patch import patch_app, patch_css, patch_index, main


APP = """'use strict';
const getArtist = (id) => state.data.artists.find(a=>a.id===id);
const formatDay = (d) => new Intl.DateTimeFormat('fr-FR',{weekday:'long',day:'numeric',month:'long',timeZone:'UTC'}).format(day(d));
function eventStatus(e){return e.status==='confirmed'?'Confirmé':e.status==='announced'?'Annoncé':e.status==='postponed'?'Reporté':'Annulé';}
if(e.ticketUrl)body.append(element('p'),externalLink('Billetterie directe',e.ticketUrl));
const aliases=[a.name,...(a.aliases||[])].map(norm);
const concerts=state.data.events.filter(e=>e.artistIds.includes(a.id)).sort((x,y)=>x.date.localeCompare(y.date));
return state.data.events.filter(e=>{const v=getVenue(e.venueId);if(!v)return false;if(from&&e.date<from||to&&e.date>to)return false;});
const footer=element('div','card-bottom'),status=element('span','confirmed','● '+eventStatus(e)),more=element('button');
$('#artists-count').textContent=new Set(data.events.flatMap(e=>e.artistIds)).size;
window.PREEXISTING_UI = true;
"""
CSS = """.confirmed{font-size:11px;font-weight:800;color:#76d9a0}
.event-card{padding:17px}
"""
INDEX = '<link href="styles.css?v=old" rel="stylesheet"><script src="app.js?v=old" defer></script>'


class ConcertSiteStatusPatchTests(unittest.TestCase):
    def test_strict_patch_for_cancelled_badge_year_and_alias_search(self):
        result = patch_app(APP)
        self.assertIn("year:'numeric'", result)
        self.assertIn("?'Reporté':'ANNULÉ'", result)
        self.assertIn("e.status==='cancelled'&&!query", result)
        self.assertIn("e.artistIds.some(id=>sameArtist(id,a.id))", result)
        self.assertIn("filter(x=>sameArtist(x.id,a.id))", result)
        self.assertIn("map(canonicalArtistId)", result)
        self.assertIn("'les-ramoneurs-de-menhirs': 'les-ramoneurs-de-menhir'", result)
        self.assertIn("Voir la source de l’annulation", result)
        self.assertIn("e.status!=='cancelled'&&e.ticketUrl", result)
        self.assertIn("status=element('span',['confirmed','announced','postponed','cancelled']", result)
        self.assertIn("window.PREEXISTING_UI = true;", result)

    def test_refuses_modified_unknown_and_duplicate_code(self):
        with self.assertRaisesRegex(ValueError, "ancre absente ou ambiguë"):
            patch_app(APP.replace("const getArtist", "const getPerformer"))
        with self.assertRaisesRegex(ValueError, "ancre absente ou ambiguë"):
            patch_app(APP + "const getArtist = (id) => state.data.artists.find(a=>a.id===id);")
        with self.assertRaises(ValueError):
            patch_app(patch_app(APP))

    def test_css_and_index_are_targeted(self):
        css = patch_css(CSS)
        self.assertIn(".cancelled{", css)
        self.assertIn(".announced{", css)
        self.assertIn(".postponed{", css)
        self.assertIn(".event-card{padding:17px}", css)
        updated_index = patch_index(INDEX)
        self.assertEqual(updated_index.count("status-alias-20261113"), 2)
        with self.assertRaises(ValueError):
            patch_css(patch_css(CSS))
        with self.assertRaises(ValueError):
            patch_index('<script src="app.js?v=old"></script>')

    def test_only_known_identity_equivalence_is_approved(self):
        result = patch_app(APP)
        self.assertEqual(result.count("'les-ramoneurs-de-menhirs': 'les-ramoneurs-de-menhir'"), 1)
        self.assertNotIn("s.replace(/s$/", result)
        self.assertNotIn("match any artist", result)


if __name__ == "__main__":
    unittest.main()
