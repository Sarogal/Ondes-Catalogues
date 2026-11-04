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
