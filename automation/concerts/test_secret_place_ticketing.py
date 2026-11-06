"""Offline tests; no network, no live approval and no catalogue write."""
import datetime as dt
import unittest
import secret_place_ticketing as s

VENUE_HTML = '''<a href="/fr/events/uuhai">UUHAI</a>
<a href="https://evil.example/fr/events/not-allowed">Bad</a>
<a href="/fr/events/uuhai?tracking=1">Tracking</a>
<a href="/fr/events/vault-of-metal-secret-place-open-air">Festival</a>'''
PAGE = '''<body><section><h1>Uuhai</h1>Par SECRET PLACE
<p>sam 3 avr. 2027 de 19:00 à 23:59</p>
<p>SECRET PLACE</p><p>25 Rue Saint Exupery, 34430 Saint-Jean-de-Védas, France</p>
</section><section><p>Line up</p><p>Uuhai</p>
<p>Organisé par</p><p>SECRET PLACE</p>
<p>Vibe</p>Metal</section></body>'''
URL='https://r.shotgun.live/fr/events/uuhai'


def catalogue():
    return {'schemaVersion':1,'mode':'preview-public-unlisted',
            'artists':[{'id':'uuhai','name':'UUHAI'}],
            'events':[{'date':'2027-04-03','venueId':s.VENUE_ID,'artistIds':['uuhai'],
                       'officialUrl':'https://shotgun.live/fr/events/uuhai'}]}


class SourceChecks(unittest.TestCase):
    def test_exact_official_ticket_page(self):
        v=s.parse_detail(PAGE,URL,dt.date(2026,11,2))
        self.assertEqual(v['date'],'2027-04-03')
        self.assertEqual(v['time'],'19:00')
        self.assertEqual(v['artists'],['Uuhai'])
        self.assertFalse(v['publicationAllowed'])

    def test_reject_unknown_date_or_year(self):
        with self.assertRaises(ValueError):
            s.parse_detail(PAGE.replace('2027',''),URL,dt.date(2026,11,2))

    def test_reject_unknown_organizer(self):
        with self.assertRaises(ValueError):
            s.parse_detail(PAGE.replace('Par SECRET PLACE','Par PRIVATE VENUE'),URL,dt.date(2026,11,2))

    def test_reject_wrong_venue_or_genre(self):
        with self.assertRaises(ValueError):
            s.parse_detail(PAGE.replace('34430','75001'),URL,dt.date(2026,11,2))
        with self.assertRaises(ValueError):
            s.parse_detail(PAGE.replace('Metal</section>','Pop</section>'),URL,dt.date(2026,11,2))

    def test_exact_host_and_url_path_required(self):
        self.assertFalse(s.valid_event_url('https://r.shotgun.live/fr/events/uuhai?track=1'))
        self.assertFalse(s.valid_event_url('https://evil.example/fr/events/uuhai'))
        self.assertFalse(s.valid_event_url('http://r.shotgun.live/fr/events/uuhai'))

    def test_public_event_remains_duplicate_not_new(self):
        a=s.parse_detail(PAGE,URL,dt.date(2026,11,2))
        review=s.compare_to_catalogue(a,catalogue(),[{'day':3,'month':4,'title':'UUHAI'}])
        self.assertEqual(review['reviewStatus'],'existing-in-catalogue')
        self.assertFalse(review['publicationAllowed'])

    def test_ticket_not_published_without_independent_review(self):
        a=s.parse_detail(PAGE,URL,dt.date(2026,11,2))
        v=catalogue();v['events']=[]
        review=s.compare_to_catalogue(a,v,[])
        self.assertEqual(review['reviewStatus'],'needs-independent-review')
        self.assertFalse(review['publicationAllowed'])
        self.assertFalse(review['calendarCorroborated'])

    def test_festival_not_a_concert(self):
        with self.assertRaises(ValueError):
            s.parse_detail(PAGE.replace('<h1>Uuhai</h1>',
                          '<h1>Secret Place Open Air Festival</h1>'),
                          URL,dt.date(2026,11,2))

    def test_partner_leads_remain_unpublishable_when_shotgun_unavailable(self):
        registry={'items':{
            'a':{'candidate':{'source':'third_party_calendar_lead',
                'venue':'Secret Place','date':'2026-12-11',
                'name':'Les Metalleux Ont Du Coeur #3',
                'candidateId':'a','publicationAllowed':False}},
            'b':{'candidate':{'source':'third_party_calendar_lead',
                'venue':'Secret Place','date':'2027-04-03',
                'name':'UUHAI','candidateId':'b','publicationAllowed':False}},
            'c':{'candidate':{'source':'third_party_calendar_lead',
                'venue':'Secret Place','date':'2027-07-30',
                'name':'Secret Place Open Air','candidateId':'c',
                'publicationAllowed':False}},
            'd':{'candidate':{'source':'third_party_calendar_lead',
                'venue':'Le Ferrailleur','date':'2027-07-30',
                'name':'Unrelated Band','publicationAllowed':False}},
        }}
        result=s.held_partner_leads(registry,catalogue(),dt.date(2026,11,2))
        self.assertEqual(result['total'],3)
        self.assertEqual(result['missingDateToReview'],1)
        self.assertEqual(result['sameDayToReview'],1)
        self.assertEqual(result['excluded'],1)
        self.assertFalse(result['publicationAllowed'])
        self.assertTrue(all(x['publicationAllowed'] is False for x in result['leads']))

    def test_partner_feed_must_not_override_cancelled_or_published_status(self):
        reg={'items':{
            'x':{'candidate':{'source':'third_party_calendar_lead',
                'venue':'Secret Place','date':'2026-12-11',
                'name':'Les Metalleux Ont Du Coeur #3',
                'candidateId':'x','publicationAllowed':False,
                'cancellationNotice':True}},
            'y':{'candidate':{'source':'third_party_calendar_lead',
                'venue':'Secret Place','date':'2026-12-11',
                'name':'Same Day','candidateId':'y','publicationAllowed':True}},
        }}
        report=s.held_partner_leads(reg,catalogue(),dt.date(2026,11,2))
        self.assertEqual(report['total'],0)

    def test_new_band_same_day_never_called_a_confirmed_duplicate(self):
        cat=catalogue()
        cat['events'].append({'date':'2026-12-11','venueId':s.VENUE_ID,
                              'title':'Known Night','artistIds':[]})
        data={'items':{'x':{'candidate':{
            'source':'third_party_calendar_lead','venue':'Secret Place',
            'date':'2026-12-11','name':'New Independent Night',
            'candidateId':'x','publicationAllowed':False}}}}
        report=s.held_partner_leads(data,cat,dt.date(2026,11,2))
        self.assertEqual(report['leads'][0]['status'],'same-day-review')
        self.assertEqual(report['leads'][0]['sameDayPublishedTitles'],['Known Night'])

    def test_bounded_review_and_429_held(self):
        v=catalogue()
        res=s.preview(VENUE_HTML,v,[],dt.date(2026,11,2),get=lambda u,r: (_ for _ in ()).throw(OSError('429')),limit=8)
        self.assertLessEqual(res['checked'],3)
        self.assertTrue(res['results'])
        self.assertEqual(res['held'],res['checked'])
        self.assertFalse(res['publicationAllowed'])


if __name__=='__main__':
    unittest.main()
