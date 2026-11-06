"""Offline guards for the exact-Infomaniak app.js ticket widget patch."""
from hashlib import sha256
from unittest import TestCase, main, mock

from infomaniak_ticket_patch import patch, TARGET, SLOT

FIXTURE = f"const start=true;\n{TARGET}\nconst bg={{}};bg.innerHTML=`<article>{SLOT}\n}}\n"


class PatchSafetyTests(TestCase):
    def test_refuses_any_unrecognized_production_bytes(self):
        with self.assertRaisesRegex(ValueError, "production a change"):
            patch(b"unrelated javascript")

    def test_inserts_exactly_one_safe_conditional_slot(self):
        original = FIXTURE.encode('utf-8')
        with mock.patch('infomaniak_ticket_patch.EXPECTED_APP_SHA', sha256(original).hexdigest()):
            result = patch(original).decode('utf-8')
        self.assertEqual(result.count('function openFestival(f,push){'), 1)
        self.assertEqual(result.count('function ensureFestivalTicketWidget(){'), 1)
        self.assertEqual(result.count('ensureFestivalTicketWidget().then(ok=>'), 1)
        self.assertIn('f?.ticketAvailability?', result)
        self.assertIn('if(!ok||!ticketSlot.isConnected)return;', result)
        self.assertIn('ticketSlot.remove()', result)
        self.assertIn('document.body.appendChild(bg);', result)
        self.assertNotIn('innerHTML=ticket', result)

    def test_ambiguous_modal_anchor_rejected(self):
        original = (FIXTURE+SLOT).encode('utf-8')
        with mock.patch('infomaniak_ticket_patch.EXPECTED_APP_SHA', sha256(original).hexdigest()):
            with self.assertRaisesRegex(ValueError, "Structure de openFestival inconnue"):
                patch(original)

    def test_rejects_applying_patch_twice(self):
        original = FIXTURE.encode('utf-8')
        with mock.patch('infomaniak_ticket_patch.EXPECTED_APP_SHA', sha256(original).hexdigest()):
            patched = patch(original)
        with self.assertRaises(ValueError):
            patch(patched)


if __name__ == '__main__':
    main()
