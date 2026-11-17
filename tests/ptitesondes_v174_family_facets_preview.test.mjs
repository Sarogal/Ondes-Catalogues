// Offline regression tests for the isolated v173 -> v174 preview. Never publish.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const ORIGINAL=fs.readFileSync('previews/ptitesondes/sorties-v173-nonmusic-preview.js','utf8');
const CANDIDATE=fs.readFileSync('previews/ptitesondes/sorties-v174-family-facets-preview.js','utf8');
const CATS={
  'lecture-jeunesse':['Lecture jeunesse','lecture','📚','pt-pin-lecture'],
  'atelier-numerique':['Atelier numérique','numerique','💻','pt-pin-numerique'],
  'lecture-cinema':['Lecture et cinéma','cinema-jeunesse','🎬','pt-pin-cinema-jeunesse'],
  'jeux-famille':['Jeux en famille','jeux','🎲','pt-pin-jeux']
};

function segment(source,before,after) {
  const a=source.indexOf(before),b=source.indexOf(after,a+before.length);
  assert.ok(a>=0 && b>a,'Expected exact source anchors: '+before);
  return source.slice(a,b);
}
function harness(){
  const categories={
    value:'all',options:[
      {value:'all',textContent:'Toutes catégories'},
      {value:'concert',textContent:'Concert'},
      {value:'conte-musical',textContent:'Conte musical'},
      {value:'autre',textContent:'Autre'}],
    addEventListener(){},
    add(option,before){
      const pos=this.options.indexOf(before);
      this.options.splice(pos<0?this.options.length:pos,0,option);
    }
  };
  const text={value:'',addEventListener(){}};
  const age={value:'all',addEventListener(){}};
  const n=()=>({hidden:false,textContent:'',innerHTML:'',addEventListener(){}});
  const els={
    'outings-search':text,'outings-age':age,'outings-category':categories,
    'outings-reset':n(),'outings-count':n(),'outings-updated':n(),
    'outings-list':n(),'outings-empty':n()
  };
  const document={
    readyState:'complete',head:null,
    getElementById(id){return els[id]||null;},
    querySelectorAll(){return [];},querySelector(){return null;},
    createElement(){return {value:'',textContent:''};},
    addEventListener(){}
  };
  const window={addEventListener(){}};
  const context=vm.createContext({document,window,location:{hash:''},
    console,Intl,Date,setTimeout,clearTimeout});
  const needle='  load();\n})();';
  assert.equal(CANDIDATE.split(needle).length,2);
  const injected=[
    '  window.__qa={',
    '    youthCategories,installYouthCategoryOptions,installFamilyFacetOptions,\n    familyFacetOptions,familyFacetByCategory,familyAppearance,categoryMatches,categoryGroup,categoryEmoji,',
    '    ageMatches,filterEvents,eventTerritory,matchesTerritory,toFeatureCollection,',
    '    eventCard,popupHtml,setEvents(rows){events=rows;},',
    '    setActiveTerritory(value){activeTerritory=value;}',
    '  };',
    '})();'
  ].join('\n');
  vm.runInContext(CANDIDATE.replace(needle,injected),context,{timeout:1000});
  return {api:window.__qa,categories,text,age};
}

test('Territorial functions, historical ages and site loader stay unchanged',()=>{
  assert.equal(segment(CANDIDATE,'  const territories = Object.freeze({','  const emptyCollection'),
    segment(ORIGINAL,'  const territories = Object.freeze({','  const emptyCollection'));
  for(const [begin,end] of [
    ['  function ageMatches(event, filter) {','  function periodMatches(event, filter) {'],
    ['  function eventTerritory(event) {','  function filterEvents() {'],
    ['  function popupHtml(event) {','  function toFeatureCollection(filtered) {']
  ]){
    assert.equal(segment(CANDIDATE,begin,end),segment(ORIGINAL,begin,end));
  }
  assert.ok(CANDIDATE.includes('function installTerritorySelect()'));
  assert.ok(CANDIDATE.includes('window.PtitesOndesLoadSorties'));
  assert.ok(CANDIDATE.includes('load();'));
});

test('Four youth category options are inserted exactly once before Autre',()=>{
  assert.doesNotThrow(()=>new vm.Script(CANDIDATE));
  const {api,categories}=harness();
  const values=categories.options.map(x=>x.value);
  for(const [slug,[label]] of Object.entries(CATS)){
    assert.equal(values.filter(x=>x===slug).length,1);
    assert.equal(categories.options.find(x=>x.value===slug).textContent,label);
    assert.ok(values.indexOf(slug)<values.indexOf('autre'));
  }
  const count=categories.options.length;
  api.installYouthCategoryOptions();
  assert.equal(categories.options.length,count);
  assert.deepEqual(values.slice(0,3),['all','concert','conte-musical']);
});

test('Markers use the four explicit nonmusical pins',()=>{
  const {api}=harness();
  for(const [slug,[,group,emoji,pin]] of Object.entries(CATS)){
    assert.equal(api.categoryGroup(slug),group);
    assert.equal(api.categoryEmoji(slug),emoji);
    assert.ok(CANDIDATE.includes("'"+pin+"'"));
    assert.ok(CANDIDATE.includes("'"+group+"','"+pin+"'"));
  }
  assert.equal(api.categoryGroup('concert'),'concert');
  assert.equal(api.categoryEmoji('concert'),'🎶');
  assert.equal(api.categoryGroup('conte-musical'),'conte');
});

test('Existing territorial filters, age ranges and precise category search stay strict',()=>{
  const {api,categories,text,age}=harness();
  const day=new Date(Date.now()+12*86400000).toISOString().slice(0,10);
  const ev=(id,category,lat,lng,options={})=>({
    id,title:id,category,category_label:options.label||id,
    date_start:day,date_end:day,lat,lng,time:'09:00',
    age_label:options.age_label||'En famille',age_min:options.age_min??null,
    age_max:options.age_max??null,city:options.city||'Le Gosier',
    region:options.region||'Guadeloupe',department:'971',
    venue:'Médiathèque Raoul Georges Nicolo',
    source_url:'https://example.org/example',price:null,description:'Sortie jeunesse'
  });
  const data=[
    ev('Mon doudou','lecture-jeunesse',16.20547,-61.48950,
      {label:'Lecture jeunesse',age_max:3,age_label:'Jusqu’à 3 ans'}),
    ev('Code','atelier-numerique',16.20547,-61.48950,
      {label:'Atelier numérique',age_min:8,age_label:'Dès 8 ans'}),
    ev('Jeux','jeux-famille',-20.89270,55.45130,
      {region:'La Réunion',city:'Saint-Denis'}),
    ev('Musique','concert',43.61,3.88,
      {region:'Occitanie',city:'Montpellier'})
  ];
  api.setEvents(data);
  api.setActiveTerritory('guadeloupe');
  categories.value='lecture-jeunesse';age.value='0-3';
  assert.deepEqual(Array.from(api.filterEvents(),x=>x.id),['Mon doudou']);
  age.value='10-plus';assert.equal(api.filterEvents().length,0);
  age.value='all';categories.value='atelier-numerique';
  assert.deepEqual(Array.from(api.filterEvents(),x=>x.id),['Code']);
  text.value='numerique';assert.equal(api.filterEvents().length,1);
  text.value='';categories.value='all';assert.equal(api.filterEvents().length,2);
  api.setActiveTerritory('reunion');
  assert.deepEqual(Array.from(api.filterEvents(),x=>x.id),['Jeux']);
  api.setActiveTerritory('metropole');
  assert.deepEqual(Array.from(api.filterEvents(),x=>x.id),['Musique']);
  assert.equal(api.toFeatureCollection(data).features.length,4);
  assert.ok(api.eventCard(data[0]).includes('Voir conditions'));
});

test('Legacy pins retain their original group classification',()=>{
  const {api}=harness();
  assert.equal(api.categoryGroup('eveil-musical'),'eveil');
  assert.equal(api.categoryGroup('atelier-musical'),'atelier');
  assert.equal(api.categoryGroup('conte'),'conte');
  assert.equal(api.categoryEmoji('atelier-musical'),'🥁');
  assert.equal(api.categoryEmoji('conte-musical'),'📖');
  assert.equal(api.categoryEmoji('eveil-musical'),'🎵');
});

const NEW_CATEGORIES={
  'atelier-creatif':['creatif','🎨','pt-pin-creatif','atelier'],
  'atelier-scientifique':['science','🔬','pt-pin-science','atelier'],
  'spectacle-jeunesse':['spectacle','🎭','pt-pin-spectacle','spectacle'],
  'cinema-jeunesse':['cinema-jeunesse','🎬','pt-pin-cinema-jeunesse','cinema'],
  'sortie-nature':['nature','🌳','pt-pin-nature','nature'],
  'animaux-ferme':['animaux','🐾','pt-pin-animaux','nature'],
  'musee-patrimoine':['culture','🏛️','pt-pin-culture','culture'],
  'fete-familiale':['fete','🎈','pt-pin-fete','evenement'],
  'activite-sportive':['sport','⚽','pt-pin-sport','sport']
};

test('Nine family facets and four exact Gosier categories installed once',()=>{
  const {api,categories}=harness();
  const values=categories.options.map(x=>x.value);
  const facets=['lecture','atelier','cinema','jeux','spectacle',
    'nature','culture','evenement','sport'];
  assert.equal(api.familyFacetOptions.length,9);
  for(const facet of facets){
    const value='family:'+facet;
    assert.equal(values.filter(v=>v===value).length,1);
    assert.ok(values.indexOf(value)<values.indexOf('autre'));
  }
  for(const slug of Object.keys(CATS)){
    assert.equal(values.filter(v=>v===slug).length,1);
  }
  const oldCount=categories.options.length;
  api.installFamilyFacetOptions();
  api.installYouthCategoryOptions();
  assert.equal(categories.options.length,oldCount);
  assert.equal(Object.keys(api.familyFacetByCategory).length,13);
});

test('Nine new category markers and pins have distinct family visuals',()=>{
  const {api}=harness();
  for(const [slug,[group,emoji,pin,facet]] of Object.entries(NEW_CATEGORIES)){
    assert.equal(api.categoryGroup(slug),group);
    assert.equal(api.categoryEmoji(slug),emoji);
    assert.equal(api.familyFacetByCategory[slug],facet);
    assert.ok(CANDIDATE.includes("'"+pin+"'"));
    assert.ok(CANDIDATE.includes("'"+group+"','"+pin+"'")||
      (pin==='pt-pin-spectacle'&&CANDIDATE.includes("'pt-pin-spectacle'")));
  }
  assert.equal(api.categoryEmoji('concert'),'🎶');
  assert.equal(api.categoryGroup('atelier-musical'),'atelier');
});

test('Broad family facets match only declared family types, never musical tracks',()=>{
  const {api}=harness();
  assert.equal(api.categoryMatches('atelier-creatif','family:atelier'),true);
  assert.equal(api.categoryMatches('atelier-scientifique','family:atelier'),true);
  assert.equal(api.categoryMatches('atelier-numerique','family:atelier'),true);
  assert.equal(api.categoryMatches('atelier-musical','family:atelier'),false);
  assert.equal(api.categoryMatches('concert','family:atelier'),false);
  assert.equal(api.categoryMatches('animaux-ferme','family:nature'),true);
  assert.equal(api.categoryMatches('lecture-cinema','family:cinema'),true);
  assert.equal(api.categoryMatches('cinema-jeunesse','family:cinema'),true);
  assert.equal(api.categoryMatches('spectacle-jeunesse','spectacle-jeunesse'),true);
  assert.equal(api.categoryMatches('concert','all'),true);
  assert.equal(api.categoryMatches('concert','family:unknown'),false);
});

test('Filter uses category facet with existing territory and age controls',()=>{
  const {api,categories,age}=harness();
  const future=new Date(Date.now()+12*86400000).toISOString().slice(0,10);
  const ev=(id,category,lat,lng,ageMin=5)=>({
    id,title:id,category,category_label:category,
    date_start:future,date_end:future,lat,lng,time:'10:00',
    age_label:'Dès '+ageMin+' ans',age_min:ageMin,
    age_max:null,city:'Montpellier',region:'Occitanie',
    department:'Hérault (34)',venue:'Lieu de test',price:null,
    source_url:'https://example.org/official',description:'SYNTHETIC only'
  });
  api.setEvents([
    ev('Atelier peinture','atelier-creatif',43.61,3.88,5),
    ev('Atelier sciences','atelier-scientifique',43.62,3.87,8),
    ev('Concert','concert',43.62,3.88,5),
    ev('Atelier musical','atelier-musical',43.63,3.88,5),
    ev('Activité nature','sortie-nature',16.20547,-61.48950,6)
  ]);
  api.setActiveTerritory('metropole');
  categories.value='family:atelier';age.value='all';
  assert.deepEqual(Array.from(api.filterEvents(),x=>x.id),
    ['Atelier peinture','Atelier sciences']);
  age.value='0-3';assert.equal(api.filterEvents().length,0);
  age.value='all';categories.value='all';
  assert.equal(api.filterEvents().length,4);
  api.setActiveTerritory('guadeloupe');categories.value='family:nature';
  assert.deepEqual(Array.from(api.filterEvents(),x=>x.id),['Activité nature']);
});

test('No catalogue publisher or geographic/age logic was changed by this candidate',()=>{
  for(const [start,end] of [
    ['  const territories = Object.freeze({','  const emptyCollection'],
    ['  function ageMatches(event, filter) {','  function periodMatches(event, filter) {'],
    ['  function eventTerritory(event) {','  function filterEvents() {'],
    ['  function popupHtml(event) {','  function toFeatureCollection(filtered) {']
  ]){
    // The filter function is intentionally changed; geographic helper itself
    // remains identical and its segment ends at the first filter definition.
    if(start.includes('eventTerritory')){
      const limit='  function filterEvents() {';
      const a=segment(ORIGINAL,start,limit);
      const b=segment(CANDIDATE,start,limit);
      assert.equal(a,b);
    }else{
      assert.equal(segment(ORIGINAL,start,end),segment(CANDIDATE,start,end));
    }
  }
  assert.ok(!CANDIDATE.includes('ptitesondes.patch.v1'));
  assert.ok(!CANDIDATE.includes('publication_ready=true'));
  assert.ok(CANDIDATE.includes('window.PtitesOndesLoadSorties'));
});
