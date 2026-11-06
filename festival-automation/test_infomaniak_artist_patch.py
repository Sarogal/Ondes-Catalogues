"""Strict offline tests for artist clickthrough patch; no network or site writes."""
from hashlib import sha256
from unittest import TestCase, mock

from infomaniak_artist_patch import (
    ANCHOR, ARCHIVE_ANCHOR, HISTORY, LINEUP, MODAL_ANCHOR, patch
)

FIXTURE = (
    "let festivalTicketWidgetPromise = null;\n"
    + MODAL_ANCHOR + LINEUP + "\n"
    + "ensureFestivalTicketWidget().then(ok=>{});\n"
    + ARCHIVE_ANCHOR + HISTORY + "\n"
    + ANCHOR + "\n"
)


class ArtistIntegrationTests(TestCase):
    def run_patch_on_fixture(self, source=FIXTURE):
        raw=source.encode("utf-8")
        with mock.patch("infomaniak_artist_patch.EXPECTED_SHA",sha256(raw).hexdigest()):
            return patch(raw).decode("utf-8")

    def test_refuses_unrecognized_production(self):
        with self.assertRaisesRegex(ValueError,"Empreinte app.js inattendue"):
            patch(b"another app.js")

    def test_clickable_artist_buttons_in_both_modals(self):
        result=self.run_patch_on_fixture()
        self.assertEqual(result.count('data-go-artist='),2)
        self.assertEqual(result.count('go-artist-link'),2)
        self.assertIn('function openFestival(f,push){ensureGoArtistDatesStyles();',result)
        self.assertIn('function openHistoricalFestival(f,push=true){ensureGoArtistDatesStyles();',result)
        self.assertIn('void openGoArtistDates(button.dataset.goArtist,button);',result)

    def test_preserves_ticket_integration_and_non_artist_content(self):
        result=self.run_patch_on_fixture()
        self.assertIn('ensureFestivalTicketWidget().then(ok=>{});',result)
        self.assertIn('let festivalTicketWidgetPromise = null;',result)
        self.assertIn('function ensureGoArtistDates(){',result)
        self.assertIn('if(!ok||!trigger.isConnected)',result)
        self.assertIn("script.onerror=()=>resolve(false)",result)
        self.assertIn("https://sarogal.github.io/Ondes-Catalogues/grossesondes/",result)

    def test_rejects_missing_or_ambiguous_anchors(self):
        with self.assertRaisesRegex(ValueError,"Ancrage absent ou ambigu"):
            self.run_patch_on_fixture(FIXTURE.replace(HISTORY,""))
        with self.assertRaisesRegex(ValueError,"Ancrage absent ou ambigu"):
            self.run_patch_on_fixture(FIXTURE + LINEUP)

    def test_rejects_second_application(self):
        output=self.run_patch_on_fixture().encode()
        with self.assertRaises(ValueError):
            patch(output)

    def test_preserves_UTF8_group_names(self):
        output=self.run_patch_on_fixture()
        self.assertIn('name',output)
        self.assertIn('esc(name)',output)
        self.assertIn('type="button"',output)
