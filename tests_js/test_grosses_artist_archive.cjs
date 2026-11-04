'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {collectAppearances, classify} = require('../docs/grossesondes/artist-dates.js');

test('historical source adds dated festival appearances but not invented concert dates', () => {
  const folder=path.join(__dirname,'../docs/grossesondes');
  const festivals=JSON.parse(fs.readFileSync(path.join(folder,'festivals.json'),'utf8'));
  const concerts=JSON.parse(fs.readFileSync(path.join(folder,'concerts.json'),'utf8'));
  const history=JSON.parse(fs.readFileSync(path.join(folder,'festival-history.json'),'utf8'));
  const before=collectAppearances('Klone', festivals, concerts);
  const after=collectAppearances('Klone', festivals, concerts, history, '2026-11-04');
  assert.equal(after.concerts.length,before.concerts.length);
  const amarok=after.festivals.find(f => f.historical && f.title==='Amarok Metal Fest');
  assert.ok(amarok,'Known documented historical festival should be discoverable');
  assert.equal(amarok.date,'2026-02-27');
  assert.equal(amarok.end,'2026-02-28');
  assert.equal(amarok.exact,false,'Without day-specific lineup the passage day is unknown');
  assert.equal(classify(after.all,'2026-11-04').upcoming.filter(f=>f.historical).length,0);
  assert.equal(new Set(after.all.map(f=>f.key)).size,after.all.length);
});

test('duplicate current edition wins and uncertain historic appearances stay hidden', () => {
  const artist={schemaVersion:1,artists:[{id:'groupe-a',name:'Groupe A',aliases:[]}],
    venues:[],events:[]};
  const live={schema:1,festivals:[{slug:'metal-ancien-2025',
    name:'Festival Metal Ancien', city:'Albi',startDate:'2025-05-01',
    endDate:'2025-05-02',lineup:['Groupe A']}]};
  const h={schema:2,knownFestivals:[
    {slug:'metal-ancien',name:'Festival Metal Ancien',city:'Albi',
     startDate:'2025-05-01',endDate:'2025-05-02',lastKnownYear:2025,
     lineup:['Groupe A'],verificationStatus:'Édition documentée',
     source:'https://festival.example/archives'},
    {slug:'metal-nouveau',name:'Festival Metal Nouveau',city:'Toulouse',
     startDate:'2025-06-01',endDate:'2025-06-03',lastKnownYear:2025,
     lineup:['Groupe A'],verificationStatus:'Édition documentée',
     source:'https://festival.example/archives2'},
    {slug:'metal-douteux',name:'Festival Metal Douteux',city:'Lyon',
     startDate:'2025-07-01',endDate:'2025-07-03',lastKnownYear:2025,
     lineup:['Groupe A'],verificationStatus:'Dernière édition à vérifier',
     source:'https://festival.example/douteux'},
    {slug:'metal-futur',name:'Festival Metal Futur',city:'Paris',
     startDate:'2027-08-01',endDate:'2027-08-02',lastKnownYear:2027,
     lineup:['Groupe A'],verificationStatus:'Édition documentée',
     source:'https://festival.example/futur'}
  ]};
  const result=collectAppearances('Groupe A',live,artist,h,'2026-11-04');
  assert.equal(result.concerts.length,0);
  assert.equal(result.festivals.length,2);
  const old=result.festivals.find(f => f.historical);
  assert.equal(old.title,'Festival Metal Nouveau');
  assert.equal(old.exact,false);
  assert.equal(old.date,'2025-06-01');
  assert.equal(old.end,'2025-06-03');
  assert.equal(result.festivals.filter(f => f.title==='Festival Metal Ancien').length,1);
});
