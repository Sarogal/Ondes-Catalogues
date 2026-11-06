#!/usr/bin/env python3
"""Secret Place venue-ticket cross-check; intentionally read-only.

Never writes approvals, never infers a year from Wix day/month calendar cells,
and never promotes a ticketing listing by itself into a publishable concert.
The remote venue index and detail pages must both be first-party-associated.
"""
from __future__ import annotations

import argparse
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib import robotparser
from zoneinfo import ZoneInfo

VENUE_URL = 'https://r.shotgun.live/fr/venues/secret-place'
HOST = 'r.shotgun.live'
VENUE_ID = 'secret-place-saint-jean-de-vedas'
CLOUD = 'https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json'
RAW = 'https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/main/docs/grossesondes/concerts.json'
AGENT = 'GrossesOndesConcertWatch/1.0 (private read-only preview)'
MONTHS = dict(zip(('jan', 'fev', 'mar', 'avr', 'mai', 'jun', 'jul',
                   'aou', 'sep', 'oct', 'nov', 'dec'), range(1, 13)))
DATE_RE = re.compile(r'\b(?:lun|mar|mer|jeu|ven|sam|dim)\.?\s+(\d{1,2})\s+'
                     r'([a-z]+)\.?\s+(20\d{2})\s+de\s+'
                     r'((?:[01]\d|2[0-3]):[0-5]\d)\b')
GENRE_RE = re.compile(r'\b(metal|metalcore|deathcore|punk|hardcore|thrash|'
                      r'doom|grind|sludge|stoner)\b')
UNSAFE_RE = re.compile(r'\b(festival|open air|annule|report[eé]|surprise|'
                       r'guest|dj set|tba)\b')


def plain(value: str) -> str:
    return (unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore')
            .decode('ascii').lower())


def norm(value: str) -> str:
    return ' '.join(re.findall(r'[a-z0-9]+', plain(value)))


def valid_event_url(url: str) -> bool:
    p = urlsplit(url)
    return (p.scheme == 'https' and p.hostname == HOST and not p.username
            and not p.password and not p.query and not p.fragment
            and bool(re.fullmatch(r'/fr/events/[a-z0-9-]{4,160}/?', p.path)))


class SourceHTML(HTMLParser):
    """Collect public visible text, H1 and exact venue-owned event paths."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes: list[str] = []
        self.headings: list[str] = []
        self.links: set[str] = set()
        self.hidden = 0
        self.h1_depth = 0
        self.h1_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden += 1
        if self.hidden:
            return
        if tag == 'h1':
            self.h1_depth += 1
            if self.h1_depth == 1:
                self.h1_parts = []
        elif self.h1_depth and tag not in ('br','img','input','meta','link'):
            self.h1_depth += 1
        if tag == 'a':
            href = dict(attrs).get('href') or ''
            url = urljoin(VENUE_URL, href)
            if valid_event_url(url):
                self.links.add(url)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden = max(0, self.hidden-1)
            return
        if self.h1_depth:
            self.h1_depth -= 1
            if self.h1_depth == 0:
                title = ' '.join(self.h1_parts)
                if title:
                    self.headings.append(title)

    def handle_data(self, data):
        if self.hidden:
            return
        value = ' '.join(data.split())
        if value:
            self.nodes.append(value)
            if self.h1_depth:
                self.h1_parts.append(value)


def parse_detail(html: str, url: str, today: dt.date) -> dict:
    if not valid_event_url(url):
        raise ValueError('URL événement non officielle')
    doc = SourceHTML()
    doc.feed(html)
    if len(doc.headings) != 1:
        raise ValueError('Titre officiel unique absent')
    title = doc.headings[0]
    if UNSAFE_RE.search(plain(title)):
        raise ValueError('Festival ou titre de programmation incomplet')
    dates = []
    date_positions = []
    for idx, row in enumerate(doc.nodes[:55]):
        m = DATE_RE.search(plain(row))
        if m and m.group(2) in MONTHS:
            day, month, year, clock = m.groups()
            dates.append((dt.date(int(year), MONTHS[month], int(day)).isoformat(), clock))
            date_positions.append(idx)
    if len(set(dates)) != 1 or not dates:
        raise ValueError('Année ou date et heure officielle non établies')
    event_date, start = dates[0]
    if dt.date.fromisoformat(event_date) < today:
        raise ValueError('Événement passé')
    nodes = [norm(x) for x in doc.nodes]
    if ('secret place' not in nodes or
        not any('25 rue saint exupery' in x and '34430' in x and
                'saint jean de vedas' in x for x in nodes)):
        raise ValueError('Adresse de la salle non confirmée')
    # Do not mistake a late 'Organisé par SECRET PLACE' for the actual
    # ticket seller's byline: it must precede the dated event header.
    title_indices = [i for i, val in enumerate(nodes[:date_positions[0]]) if val == norm(title)]
    if len(title_indices) != 1 or title_indices[0] >= date_positions[0]:
        raise ValueError('En-tête de billetterie absent')
    header = ' '.join(nodes[title_indices[0]+1:date_positions[0]])
    if not re.search(r'\bpar secret place\b', header):
        raise ValueError('Organisateur officiel absent')
    if 'line up' not in nodes or 'organise par' not in nodes:
        raise ValueError('Liste des artistes non présentée clairement')
    begin = nodes.index('line up')
    end = nodes.index('organise par', begin + 1)
    artists = doc.nodes[begin + 1:end]
    if not (1 <= len(artists) <= 5) or any(len(norm(x)) < 3 for x in artists):
        raise ValueError('Artistes incomplets ou ambigus')
    if len(set(norm(x) for x in artists)) != len(artists):
        raise ValueError('Artistes dupliqués')
    vibe = ''
    if 'vibe' in nodes:
        at = nodes.index('vibe')
        if at + 1 < len(nodes):
            vibe = doc.nodes[at+1]
    if not GENRE_RE.search(norm(vibe)):
        raise ValueError('Genre metal ou punk non explicite')
    return {'title': title, 'date': event_date, 'time': start,
            'artists': artists, 'genre': vibe, 'venueId': VENUE_ID,
            'officialTicketUrl': url, 'publicationAllowed': False}


def compare_to_catalogue(event: dict, catalogue: dict, calendar: list[dict]) -> dict:
    if catalogue.get('schemaVersion') != 1 or catalogue.get('mode') != 'preview-public-unlisted':
        raise ValueError('Catalogue public non conforme')
    date = dt.date.fromisoformat(event['date'])
    name = norm(event['title'])
    calendar_match = any(
        x.get('day') == date.day and x.get('month') == date.month
        and len(norm(x.get('title', ''))) >= 8
        and (norm(x['title']) in name or name in norm(x['title']))
        for x in calendar)
    artist_names = {a['id']: norm(a['name']) for a in catalogue['artists']}
    lineup = {norm(x) for x in event['artists']}
    exists = any(
        x['venueId'] == VENUE_ID and x['date'] == event['date']
        and (x.get('officialUrl') == event['officialTicketUrl']
             or bool({artist_names.get(i) for i in x['artistIds']} & lineup))
        for x in catalogue['events'])
    return {'event': event, 'calendarCorroborated': calendar_match,
            'reviewStatus': 'existing-in-catalogue' if exists else 'needs-independent-review',
            'publicationAllowed': False}


def fetch(url: str, robots: dict) -> str:
    if not url.startswith('https://') or urlsplit(url).hostname != HOST:
        raise ValueError('Source hors du domaine autorisé')
    if HOST not in robots:
        # Fetch robots explicitly: Python's RobotFileParser.read() can
        # interpret a 429 as allow_all. A rate-limit response must fail closed.
        with urlopen(Request('https://r.shotgun.live/robots.txt',
                             headers={'User-Agent': AGENT}), timeout=8) as response:
            if response.status != 200 or urlsplit(response.geturl()).hostname != HOST:
                raise ValueError('Robots.txt officiel indisponible')
            content = response.read(100_001)
            if len(content) > 100_000:
                raise ValueError('Robots.txt officiel trop volumineux')
        rp = robotparser.RobotFileParser()
        rp.parse(content.decode('utf-8', errors='replace').splitlines())
        robots[HOST] = rp
    if not robots[HOST].can_fetch(AGENT, url):
        raise ValueError('Accès interdit par robots.txt')
    with urlopen(Request(url, headers={'User-Agent': AGENT}), timeout=13) as response:
        if urlsplit(response.geturl()).hostname != HOST:
            raise ValueError('Redirection hors du domaine autorisé')
        raw = response.read(600001)
        if len(raw) > 600000:
            raise ValueError('Page trop volumineuse')
        return raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')


def preview(venue_html: str, catalogue: dict, calendar: list[dict], today: dt.date,
            get=fetch, limit: int=3) -> dict:
    doc = SourceHTML(); doc.feed(venue_html)
    links = sorted(doc.links)
    limit = min(max(1, limit), 3)
    start = (today.toordinal() * limit) % len(links) if links else 0
    selected = [links[(start+i) % len(links)] for i in range(min(limit, len(links)))]
    rows = []
    robots = {}
    for url in selected:
        try:
            item = parse_detail(get(url, robots), url, today)
            rows.append(compare_to_catalogue(item, catalogue, calendar))
        except Exception as exc:
            rows.append({'url': url, 'reviewStatus': 'held',
                         'reason': str(exc)[:140], 'publicationAllowed': False})
    return {'schema': 'grossesondes.concert.secretplace.ticketing.review.v1',
            'venueIndex': VENUE_URL, 'mode': 'read-only',
            'linkedEvents': len(links), 'checked': len(rows),
            'newReviewLeads': sum(r['reviewStatus']=='needs-independent-review' for r in rows),
            'held': sum(r['reviewStatus']=='held' for r in rows),
            'publicationAllowed': False, 'results': rows}



def held_partner_leads(registry: dict, catalogue: dict, today: dt.date) -> dict:
    """Independent third-party feed leads, NEVER official corroboration.

    A same-day known concert is a *possible* duplicate only; another concert
    can legitimately play the same room that day. Do not silently discard it.
    """
    if catalogue.get('schemaVersion') != 1 or catalogue.get('mode') != 'preview-public-unlisted':
        raise ValueError('Untrusted public concert catalogue')
    rows=[]
    for data in registry.get('items',{}).values():
        candidate = data.get('candidate') or {}
        if (candidate.get('source') != 'third_party_calendar_lead' or
            norm(candidate.get('venue','')) != 'secret place' or
            candidate.get('cancellationNotice') or
            candidate.get('publicationAllowed') is not False):
            continue
        try:
            when=dt.date.fromisoformat(candidate['date'])
        except (KeyError, ValueError, TypeError):
            continue
        if when < today:
            continue
        title=str(candidate.get('name') or '').strip()
        if not title:
            continue
        same_day=[e.get('title') or e.get('id','Concert publié') for e in catalogue['events']
                  if e.get('venueId')==VENUE_ID and e.get('date')==when.isoformat()]
        category=('festival-or-open-air-excluded' if
                  'festival' in norm(title).split() or 'open air' in norm(title)
                  else 'same-day-review' if same_day
                  else 'missing-date-to-review')
        rows.append({'candidateId':candidate.get('candidateId'),
                     'date':when.isoformat(),'title':title,'status':category,
                     'sameDayPublishedTitles':same_day[:5],
                     'sourceType':'third-party-only',
                     'publicationAllowed':False})
    rows.sort(key=lambda x:(x['date'],x['candidateId'] or ''))
    # Deduplicate exact normalized same-date titles, but do not collapse
    # different bands from the same calendar day.
    unique={}
    for item in rows:
        unique.setdefault((item['date'],norm(item['title'])),item)
    rows=list(unique.values())
    return {'total':len(rows),
            'missingDateToReview':sum(x['status']=='missing-date-to-review' for x in rows),
            'sameDayToReview':sum(x['status']=='same-day-review' for x in rows),
            'excluded':sum(x['status']=='festival-or-open-air-excluded' for x in rows),
            'leads':rows,'publicationAllowed':False}


def run():
    p=argparse.ArgumentParser()
    p.add_argument('--catalogue', default=CLOUD)
    p.add_argument('--report', required=True)
    p.add_argument('--registry', default=None)
    args=p.parse_args()
    result={'schema':'grossesondes.concert.secretplace.ticketing.review.v1',
            'mode':'read-only','status':'source-unavailable',
            'linkedEvents':0,'checked':0,'newReviewLeads':0,'held':0,
            'publicationAllowed':False,'results':[]}
    try:
        cat=None
        for url in (args.catalogue, RAW):
            try:
                with urlopen(url, timeout=12) as response:
                    v=json.load(response)
                if v.get('schemaVersion')==1 and v.get('mode')=='preview-public-unlisted':
                    cat=v; break
            except (OSError, ValueError, TypeError):
                pass
        if cat is None:
            result['status']='catalogue-unavailable'
        else:
            index=fetch(VENUE_URL,{})
            # Wix has no reliable event year in its month/day grid. Calendar
            # corroboration is optional and never authorizes publication.
            result=preview(index, cat, [],
                           dt.datetime.now(ZoneInfo('Europe/Paris')).date())
            result['status']='read-only-complete' if result['linkedEvents'] else 'venue-index-not-extractable'
    except Exception as exc:
        result['status']='source-unavailable:'+type(exc).__name__
    # Preserve the difference between "no new official event" and an
    # unreachable official source. The partner feed provides investigation
    # leads, not additional evidence of confirmation or publishability.
    if args.registry:
        try:
            if cat is None:
                result['secondaryLeads']={'status':'catalogue-unavailable',
                                          'publicationAllowed':False}
            else:
                registry=json.loads(Path(args.registry).read_text(encoding='utf-8'))
                result['secondaryLeads']=held_partner_leads(
                    registry,cat,dt.datetime.now(ZoneInfo('Europe/Paris')).date())
        except (OSError,ValueError,TypeError,KeyError):
            result['secondaryLeads']={'status':'unavailable',
                                      'publicationAllowed':False}
    Path(args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={k:v for k,v in result.items() if k not in ('results','secondaryLeads')}
    if 'secondaryLeads' in result:
        summary['secondaryLeadCount']=result['secondaryLeads'].get('total',0)
        summary['secondaryUnlistedDates']=result['secondaryLeads'].get('missingDateToReview',0)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    run()
