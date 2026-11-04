'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {collectAppearances, artistIdentity, classify, norm, isIso, safeHttps} =
  require('../docs/grossesondes/artist-dates.js');
const concerts = {
  schemaVersion: 1,
  artists: [
    {id:'the-great-old-ones', name:'The Great Old Ones', aliases:['T.G.O.O.']},
    {id:'mutterlein', name:'Mütterlein', aliases:[]},
    {id:'other', name:'Other Group', aliases:['Autre groupe']}
  ],
  venues: [{id:'v1', name:'Le Rockstore', city:'Montpellier'}],
  events: [
    {id:'a', title:'The Great Old Ones + Guests', date:'2026-12-05',
      artistIds:['the-great-old-ones'], venueId:'v1', status:'confirmed',
      officialUrl:'https://example.org/tgoo'},
    {id:'b', title:'Mütterlein live', date:'2026-12-16',
      artistIds:['mutterlein'], venueId:'v1', status:'confirmed'},
    {id:'c', title:'TGOO annulé', date:'2026-12-18',
      artistIds:['the-great-old-ones'], venueId:'v1', status:'cancelled'},
    {id:'d', title:'Autre groupe', date:'2026-11-12',
      artistIds:['other'], venueId:'v1', status:'confirmed'}
  ]
};
const festivals = {schema:1,festivals:[
  {slug:'ex-tenebris-2026',name:'Ex Tenebris Lux',startDate:'2026-10-02',endDate:'2026-10-31',
    city:'Montpellier',status:'Confirmé',officialSite:'https://example.org/festival',
    lineup:['The Great Old Ones','Mütterlein'],lineupByDate:{
      '2026-10-10':['The Great Old Ones'], '2026-10-28':['Mütterlein']
    }},
  {slug:'festival-2027',name:'Festival des Ondes',startDate:'2027-06-03',endDate:'2027-06-05',
    city:'Nîmes',status:'Annoncé',lineup:['The Great Old Ones','Other Group']},
  {slug:'double-2027',name:'Autre Festival',startDate:'2027-07-01',endDate:'2027-07-03',
    city:'Albi',status:'Confirmé',lineup:['T.G.O.O.'],
    lineupByDate:{'2027-07-01':['T.G.O.O.'],'2027-07-02':['T.G.O.O.']}},
  {slug:'not-tgoo',name:'Ne pas confondre',startDate:'2027-09-01',endDate:'2027-09-02',
    city:'Lyon',status:'Confirmé',lineup:['The Great Old Ones Tribute']},
  {slug:'cancelled',name:'Festival annulé',startDate:'2027-08-01',endDate:'2027-08-02',
    city:'Rennes',status:'Annulé / reporté',lineup:['The Great Old Ones']}
]};
test('matching is accent-insensitive and excludes near names', () => {
  assert.equal(norm('Mütterlein'),norm('Mutterlein'));
  assert.notEqual(norm('The Great Old Ones'),norm('The Great Old Ones Tribute'));
  assert.equal(collectAppearances('Mutterlein',festivals,concerts).concerts.length,1);
  assert.equal(collectAppearances('T.G.O.O.',festivals,concerts).concerts.length,2);
});
test('concert IDs and future festival lineup are linked in both directions', () => {
  const result=collectAppearances('The Great Old Ones',festivals,concerts);
  assert.equal(result.concerts.length,2);
  assert.equal(result.festivals.length,5);
  assert.ok(result.festivals.some(f=>f.slug==='festival-2027' && !f.exact &&
    f.date==='2027-06-03' && f.end==='2027-06-05'));
  assert.ok(!result.festivals.some(f=>f.slug==='not-tgoo'));
});
test('lineupByDate emits only proven day(s), never every day of a multi-day festival', () => {
  const result=collectAppearances('The Great Old Ones',festivals,concerts);
  const atEx=result.festivals.filter(x=>x.slug==='ex-tenebris-2026');
  assert.deepEqual(atEx.map(x=>x.date),['2026-10-10']);
  assert.ok(atEx.every(x=>x.exact));
  assert.deepEqual(result.festivals.filter(x=>x.slug==='double-2027').map(x=>x.date),
    ['2027-07-01','2027-07-02']);
});
test('lineup without per-day evidence stays an interval of unknown exact performance', () => {
  const result=collectAppearances('Other Group',festivals,concerts);
  assert.equal(result.festivals.length,1);
  assert.equal(result.festivals[0].exact,false);
  assert.equal(result.festivals[0].end,'2027-06-05');
});
test('missing artist registration still shows verified festival participation, not invented concerts', () => {
  const result=collectAppearances('A Band', {schema:1,festivals:[{
    slug:'a',name:'Festival A',startDate:null,endDate:null,lineup:['A Band']
  }]},concerts);
  assert.equal(result.concerts.length,0);
  assert.equal(result.festivals.length,1);
  assert.equal(result.festivals[0].date,null);
});
test('duplicate artist identity is ambiguous, no cross-association of concert IDs', () => {
  const double={...concerts,artists:[
    ...concerts.artists,{id:'another',name:'T.G.O.O.',aliases:[]}
  ]};
  const result=collectAppearances('T.G.O.O.',festivals,double);
  assert.equal(result.ambiguous,true);
  assert.equal(result.concerts.length,0);
  assert.equal(result.festivals.length,1);
});
test('cancelled and postponed dates are not represented as upcoming shows', () => {
  const result=collectAppearances('The Great Old Ones',festivals,concerts);
  const grouped=classify(result.all,'2026-11-04');
  assert.ok(grouped.unavailable.some(x=>x.key==='c:c'));
  assert.ok(grouped.unavailable.some(x=>x.key==='f:cancelled'));
  assert.ok(!grouped.upcoming.some(x=>x.key==='c:c'));
});
test('only safe HTTPS links are accepted; dates are strictly validated', () => {
  assert.equal(safeHttps('javascript:alert(1)'), '');
  assert.equal(safeHttps('http://example.org'), '');
  assert.equal(safeHttps('https://user:pass@example.org'), '');
  assert.equal(safeHttps('https://example.org/'), 'https://example.org/');
  assert.equal(isIso('2026-02-30'),false);
  assert.equal(isIso('2027-07-02'),true);
});
test('a single supplied artist does not match substrings inside other artist names', () => {
  const a=collectAppearances('Other',festivals,concerts);
  assert.equal(a.concerts.length,0);
  assert.equal(a.festivals.length,0);
});
