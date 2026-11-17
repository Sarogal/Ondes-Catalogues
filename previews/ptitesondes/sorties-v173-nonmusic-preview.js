(() => {
  'use strict';

  const searchInput = document.getElementById('outings-search');
  const ageSelect = document.getElementById('outings-age');
  const categorySelect = document.getElementById('outings-category');
  const periodButtons = [...document.querySelectorAll('.period-chip')];
  const resetButton = document.getElementById('outings-reset');
  const recenterButton = document.getElementById('map-recenter');
  const countEl = document.getElementById('outings-count');
  const updatedEl = document.getElementById('outings-updated');
  const listEl = document.getElementById('outings-list');
  const emptyEl = document.getElementById('outings-empty');
  const mapEl = document.getElementById('outings-map');
  const mapFallback = document.getElementById('map-fallback');
  const mapVisibleCount = document.getElementById('map-visible-count');
  const mapVisibleList = document.getElementById('map-visible-list');
  const mapVisibleEmpty = document.getElementById('map-visible-empty');

  let events = [];
  let currentPeriod = 'all';
  let currentFiltered = [];
  let map = null;
  let mapReady = false;
  let popup = null;
  let mapInitPromise = null;
  let activeTerritory = 'metropole';
  let territorySelect = null;
  const eventsById = new Map();

  const franceBounds = [[-5.5,41.2],[9.8,51.7]];
  const maxBounds = [[-14.0,37.0],[18.0,56.0]];
  // Navigation seulement : ces boîtes ne servent jamais à justifier une fiche.
  // Deux cadrages distincts : sélection des fiches et déplacement sur la carte.
  const territories = Object.freeze({
    metropole: {label:'M\u00e9tropole et Corse',view:franceBounds,limit:maxBounds},
    guadeloupe: {label:'Guadeloupe',view:[[-61.95,15.70],[-60.95,16.66]],limit:[[-62.35,15.40],[-60.55,16.98]]},
    martinique: {label:'Martinique',view:[[-61.27,14.35],[-60.75,14.96]],limit:[[-61.55,14.10],[-60.47,15.20]]},
    guyane: {label:'Guyane',view:[[-54.75,1.85],[-51.45,6.04]],limit:[[-55.30,1.35],[-50.90,6.55]]},
    reunion: {label:'La R\u00e9union',view:[[55.08,-21.45],[55.92,-20.80]],limit:[[54.80,-21.73],[56.20,-20.52]]},
    mayotte: {label:'Mayotte',view:[[44.88,-13.13],[45.46,-12.48]],limit:[[44.58,-13.43],[45.75,-12.20]]}
  });
  const emptyCollection = {type:'FeatureCollection',features:[]};

  function normalize(value) {
    return String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
  }

  function escapeHtml(value) {
    return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
  }

  function dateOnly(value) { return new Date(`${value}T12:00:00`); }
  function startOfToday() { const d = new Date(); d.setHours(0,0,0,0); return d; }

  function formatFullDate(value) {
    return new Intl.DateTimeFormat('fr-FR',{weekday:'short',day:'numeric',month:'long',year:'numeric'}).format(dateOnly(value)).replace(/^./, c => c.toUpperCase());
  }

  function formatShortDate(value) {
    const d = dateOnly(value);
    return {
      day:new Intl.DateTimeFormat('fr-FR',{day:'2-digit'}).format(d),
      month:new Intl.DateTimeFormat('fr-FR',{month:'short'}).format(d).replace('.','')
    };
  }

  function formatUpdated(value) {
    if (!value) return '';
    const d = new Date(value);
    return `Agenda mis à jour le ${new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'long',year:'numeric'}).format(d)}`;
  }

  // Catégories jeunesse non musicales : seules les fiches validées par le
  // catalogue peuvent entrer ici. Ce code UI n'accorde aucune publication.
  const youthCategories = Object.freeze([
    ['lecture-jeunesse', 'Lecture jeunesse'],
    ['atelier-numerique', 'Atelier numérique'],
    ['lecture-cinema', 'Lecture et cinéma'],
    ['jeux-famille', 'Jeux en famille']
  ]);

  function installYouthCategoryOptions() {
    if (!categorySelect) return;
    const other = Array.from(categorySelect.options).find(option => option.value === 'autre') || null;
    for (const [slug,label] of youthCategories) {
      if (Array.from(categorySelect.options).some(option => option.value === slug)) continue;
      const option = document.createElement('option');
      option.value = slug;
      option.textContent = label;
      categorySelect.add(option,other);
    }
  }

  function categoryGroup(category) {
    if (category === 'lecture-jeunesse') return 'lecture';
    if (category === 'atelier-numerique') return 'numerique';
    if (category === 'lecture-cinema') return 'cinema-jeunesse';
    if (category === 'jeux-famille') return 'jeux';
    if (category === 'eveil-musical') return 'eveil';
    if (category === 'atelier-musical') return 'atelier';
    if (category === 'concert') return 'concert';
    if (category === 'conte' || category === 'conte-musical') return 'conte';
    return 'spectacle';
  }

  function categoryEmoji(category) {
    if (category === 'lecture-jeunesse') return '📚';
    if (category === 'atelier-numerique') return '💻';
    if (category === 'lecture-cinema') return '🎬';
    if (category === 'jeux-famille') return '🎲';
    if (category === 'eveil-musical') return '🎵';
    if (category === 'atelier-musical') return '🥁';
    if (category === 'concert') return '🎶';
    if (category === 'conte' || category === 'conte-musical') return '📖';
    return '🎭';
  }

  function ageMatches(event, filter) {
    if (filter === 'all') return true;
    const min = Number.isFinite(event.age_min) ? event.age_min : 0;
    const max = Number.isFinite(event.age_max) ? event.age_max : 99;
    const ranges = {'0-3':[0,3],'3-6':[3,6],'6-10':[6,10],'10-plus':[10,99]};
    const range = ranges[filter];
    return !range || (min <= range[1] && max >= range[0]);
  }

  function periodMatches(event, filter) {
    const today = startOfToday();
    const start = dateOnly(event.date_start);
    const end = dateOnly(event.date_end || event.date_start); end.setHours(23,59,59,999);
    if (end < today) return false;
    if (filter === 'all') return true;
    if (filter === 'weekend') {
      const day = today.getDay();
      const daysToSaturday = day === 6 ? 0 : day === 0 ? -1 : 6 - day;
      const saturday = new Date(today); saturday.setDate(today.getDate() + daysToSaturday);
      const sunday = new Date(saturday); sunday.setDate(saturday.getDate() + 1); sunday.setHours(23,59,59,999);
      return start <= sunday && end >= saturday;
    }
    const days = Number(filter);
    if (Number.isFinite(days)) {
      const limit = new Date(today); limit.setDate(today.getDate() + days); limit.setHours(23,59,59,999);
      return start <= limit && end >= today;
    }
    return true;
  }

  function eventTerritory(event) {
    // Coordonnées déjà publiées/qualifiées : aucun géocodage approximatif.
    const lat = event?.lat, lng = event?.lng;
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
    for (const [key,territory] of Object.entries(territories)) {
      const [[west,south],[east,north]] = territory.view;
      if (west <= lng && lng <= east && south <= lat && lat <= north) return key;
    }
    return null;
  }

  function matchesTerritory(event) {
    const place = eventTerritory(event);
    if (place) return place === activeTerritory;
    // Une coordonnée hors des six zones connues n'est pas réassignée par défaut.
    if (Number.isFinite(event?.lat) && Number.isFinite(event?.lng)) return false;
    // Maintenir la compatibilité des fiches anciennes sans coordonnées :
    // aucune affirmation GPS, jamais d'affichage dans une zone ultramarine.
    if (activeTerritory !== 'metropole') return false;
    const explicitOverseas = ['guadeloupe','martinique','guyane','la reunion','mayotte'];
    return !explicitOverseas.includes(normalize(event?.region));
  }

  function filterEvents() {
    const q = normalize(searchInput.value);
    const age = ageSelect.value;
    const category = categorySelect.value;
    return events.filter(event => {
      const searchable = normalize([event.title,event.city,event.department,event.region,event.venue,event.description,event.category_label,event.age_label].join(' '));
      return matchesTerritory(event) && (!q || searchable.includes(q)) && (category === 'all' || event.category === category) && ageMatches(event, age) && periodMatches(event, currentPeriod);
    }).sort((a,b) => a.date_start.localeCompare(b.date_start) || (a.time || '').localeCompare(b.time || '') || a.city.localeCompare(b.city));
  }

  function eventCard(event) {
    const d = formatShortDate(event.date_start);
    const dateText = event.date_end && event.date_end !== event.date_start
      ? `Du ${new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(dateOnly(event.date_start))} au ${new Intl.DateTimeFormat('fr-FR',{day:'numeric',month:'short'}).format(dateOnly(event.date_end))}`
      : formatFullDate(event.date_start);
    const timeText = event.time ? ` · ${escapeHtml(event.time.replace(':','h'))}` : '';
    return `<article class="outing-card" data-event-id="${escapeHtml(event.id)}" id="${escapeHtml(event.id)}" tabindex="0">
      <div class="outing-date"><strong>${d.day}</strong><span>${d.month}</span></div>
      <div class="outing-main-copy">
        <div class="outing-tags"><span class="outing-tag">${escapeHtml(event.category_label)}</span><span class="outing-tag age">${escapeHtml(event.age_label || 'Famille')}</span></div>
        <h3>${escapeHtml(event.title)}</h3>
        <div class="outing-place">📍 ${escapeHtml(event.city)} · ${escapeHtml(event.venue || event.department)}</div>
        <p class="outing-desc">${escapeHtml(event.description || '')}</p>
        <div class="outing-meta"><span>📅 ${escapeHtml(dateText)}${timeText}</span><span>${escapeHtml(event.department)}</span></div>
      </div>
      <div class="outing-card-actions"><span class="outing-card-price">${escapeHtml(event.price || 'Voir conditions')}</span><a class="outing-source" href="${escapeHtml(event.source_url)}" target="_blank" rel="noopener noreferrer">Voir les infos ↗</a></div>
    </article>`;
  }

  function visibleMapEventRow(event) {
    const d = formatShortDate(event.date_start);
    const timeText = event.time ? ` · ${escapeHtml(event.time.replace(':','h'))}` : '';
    return `<button class="map-visible-row" type="button" data-map-event-id="${escapeHtml(event.id)}">
      <span class="map-visible-date"><strong>${d.day}</strong><span>${d.month}</span></span>
      <span class="map-visible-emoji" aria-hidden="true">${categoryEmoji(event.category)}</span>
      <span class="map-visible-copy">
        <strong>${escapeHtml(event.title)}</strong>
        <span>📍 ${escapeHtml(event.city)}${event.department ? ` (${escapeHtml(event.department)})` : ''}</span>
        <small>${escapeHtml(event.category_label || '')}${event.age_label ? ` · ${escapeHtml(event.age_label)}` : ''}${timeText}</small>
      </span>
      <span class="map-visible-arrow" aria-hidden="true">›</span>
    </button>`;
  }

  function eventsVisibleInMap() {
    if (!mapReady || !map) return [];
    const bounds = map.getBounds();
    return currentFiltered
      .filter(event => Number.isFinite(event.lat) && Number.isFinite(event.lng))
      .filter(event => bounds.contains([event.lng,event.lat]))
      .sort((a,b) => a.date_start.localeCompare(b.date_start)
        || (a.time || '').localeCompare(b.time || '')
        || a.city.localeCompare(b.city));
  }

  function renderVisibleMapEvents() {
    if (!mapVisibleCount || !mapVisibleList || !mapVisibleEmpty) return;
    if (!mapReady || !map) {
      mapVisibleCount.textContent = 'Carte indisponible';
      mapVisibleList.innerHTML = '';
      mapVisibleEmpty.hidden = false;
      return;
    }

    const visible = eventsVisibleInMap();
    mapVisibleCount.textContent = `${visible.length} sortie${visible.length > 1 ? 's' : ''} visible${visible.length > 1 ? 's' : ''}`;
    mapVisibleList.innerHTML = visible.map(visibleMapEventRow).join('');
    mapVisibleEmpty.hidden = visible.length !== 0;
  }

  function popupHtml(event) {
    const d = formatShortDate(event.date_start);
    const when = `${d.day} ${d.month}${event.time ? ` · ${event.time.replace(':','h')}` : ''}`;
    return `<div class="outing-popup">
      <div class="outing-popup-top"><span class="outing-popup-emoji">${categoryEmoji(event.category)}</span><div><h3>${escapeHtml(event.title)}</h3><p class="outing-popup-place">📍 ${escapeHtml(event.city)} · ${escapeHtml(event.venue || event.department)}</p></div></div>
      <div class="outing-popup-meta"><span>${escapeHtml(when)}</span><span>${escapeHtml(event.category_label)}</span><span class="age">${escapeHtml(event.age_label || 'Famille')}</span></div>
      <a href="${escapeHtml(event.source_url)}" target="_blank" rel="noopener noreferrer">Voir les informations ↗</a>
    </div>`;
  }

  function toFeatureCollection(filtered) {
    return {
      type:'FeatureCollection',
      features:filtered.filter(event => Number.isFinite(event.lat) && Number.isFinite(event.lng)).map(event => ({
        type:'Feature',
        geometry:{type:'Point',coordinates:[event.lng,event.lat]},
        properties:{
          id:event.id,
          category:event.category,
          category_group:categoryGroup(event.category),
          emoji:categoryEmoji(event.category)
        }
      }))
    };
  }

  function safeSetPaint(layerId, property, value) {
    try { map.setPaintProperty(layerId, property, value); } catch (_) {}
  }

  function safeSetLayout(layerId, property, value) {
    try { map.setLayoutProperty(layerId, property, value); } catch (_) {}
  }

  function applyPtitesOndesVectorStyle() {
    const style = map.getStyle();
    const layers = Array.isArray(style?.layers) ? style.layers : [];

    for (const layer of layers) {
      const id = String(layer.id || '');
      const sourceLayer = String(layer['source-layer'] || '');

      if (id === 'natural_earth') {
        safeSetLayout(id, 'visibility', 'none');
        continue;
      }
      if (id === 'background') {
        safeSetPaint(id, 'background-color', '#e3e6e8');
        continue;
      }

      if (/poi|housenumber|one_way_arrow|oneway/i.test(id)) {
        safeSetLayout(id, 'visibility', 'none');
        continue;
      }

      /* OpenFreeMap Liberty exclut déjà maritime=1 de ses frontières.
         On garde ce filtrage vectoriel et on ne dessine donc aucune frontière marine. */
      if (sourceLayer === 'boundary') {
        safeSetPaint(id, 'line-color', id === 'boundary_2' ? '#98a6ae' : '#b8c0c5');
        safeSetPaint(id, 'line-opacity', id === 'boundary_2' ? 0.50 : 0.28);
        continue;
      }

      if (id === 'water') {
        safeSetPaint(id, 'fill-color', '#d9eef7');
        safeSetPaint(id, 'fill-opacity', 1);
        continue;
      }
      if (sourceLayer === 'waterway') {
        safeSetPaint(id, 'line-color', '#afd7e6');
        safeSetPaint(id, 'line-opacity', 0.76);
        continue;
      }

      if (id === 'park') {
        safeSetPaint(id, 'fill-color', '#dce9dc');
        safeSetPaint(id, 'fill-opacity', 0.52);
        safeSetPaint(id, 'fill-outline-color', '#cddfcf');
        continue;
      }

      if ((sourceLayer === 'landcover' || sourceLayer === 'landuse') && layer.type === 'fill') {
        const color = /sand/i.test(id) ? '#eee5d3'
          : /wood|grass|pitch|track|cemetery/i.test(id) ? '#e2e9df'
          : '#e8e9e8';
        safeSetPaint(id, 'fill-color', color);
        safeSetPaint(id, 'fill-opacity', /residential/i.test(id) ? 0.32 : 0.40);
        continue;
      }

      if (sourceLayer === 'building' && layer.type === 'fill') {
        safeSetPaint(id, 'fill-color', '#d9dee1');
        safeSetPaint(id, 'fill-opacity', 0.46);
        safeSetPaint(id, 'fill-outline-color', '#cbd2d6');
        continue;
      }

      if (sourceLayer === 'transportation' && layer.type === 'line') {
        if (/rail/i.test(id)) {
          safeSetPaint(id, 'line-color', '#c4cbd0');
          safeSetPaint(id, 'line-opacity', 0.40);
        } else if (/casing/i.test(id)) {
          safeSetPaint(id, 'line-color', '#d4d8da');
          safeSetPaint(id, 'line-opacity', 0.50);
        } else if (/motorway/i.test(id)) {
          safeSetPaint(id, 'line-color', '#e6cfba');
          safeSetPaint(id, 'line-opacity', 0.70);
        } else if (/trunk|primary/i.test(id)) {
          safeSetPaint(id, 'line-color', '#ead9c8');
          safeSetPaint(id, 'line-opacity', 0.66);
        } else if (/secondary|tertiary/i.test(id)) {
          safeSetPaint(id, 'line-color', '#f0e5d8');
          safeSetPaint(id, 'line-opacity', 0.60);
        } else {
          safeSetPaint(id, 'line-color', '#f4f2ee');
          safeSetPaint(id, 'line-opacity', 0.54);
        }
        continue;
      }

      if (layer.type === 'symbol') {
        if (/water/i.test(id)) {
          safeSetPaint(id, 'text-color', '#739bad');
          safeSetPaint(id, 'text-halo-color', 'rgba(238,248,251,.92)');
        } else if (/country/i.test(id)) {
          safeSetPaint(id, 'text-color', '#8a9298');
          safeSetPaint(id, 'text-halo-color', 'rgba(243,244,244,.90)');
        } else if (/place|city|town|village|settlement/i.test(id) || sourceLayer === 'place') {
          safeSetPaint(id, 'text-color', '#5f7480');
          safeSetPaint(id, 'text-halo-color', 'rgba(255,252,246,.90)');
        } else if (/road|transportation/i.test(id)) {
          safeSetPaint(id, 'text-color', '#879097');
          safeSetPaint(id, 'text-halo-color', 'rgba(255,255,255,.84)');
        }
      }
    }
  }

  async function addFranceLayer() {
    const response = await fetch('assets/france-metropole.geojson',{cache:'force-cache'});
    if (!response.ok) throw new Error(`Contour France HTTP ${response.status}`);
    const france = await response.json();
    map.addSource('france-focus',{type:'geojson',data:france});

    // Place la France au-dessus des couches de landuse/landcover afin d'éviter
    // l'effet "tacheté", mais sous les routes, l'eau et les libellés.
    const styleLayers = map.getStyle()?.layers || [];
    const firstTransport = styleLayers.find(layer =>
      layer['source-layer'] === 'transportation' ||
      /^tunnel_|^road_|^bridge_/.test(String(layer.id || ''))
    );
    const beforeId = firstTransport?.id;

    map.addLayer({
      id:'france-focus-fill',
      type:'fill',
      source:'france-focus',
      paint:{'fill-color':'#fff6e8','fill-opacity':1}
    },beforeId);

    // Les couches d'eau doivent rester visibles par-dessus l'aplat France.
    // On les remonte juste avant les routes, en conservant leur ordre relatif.
    if (beforeId) {
      const waterLayers = (map.getStyle()?.layers || []).filter(layer =>
        layer.id !== 'france-focus-fill' &&
        (layer['source-layer'] === 'water' ||
         layer['source-layer'] === 'waterway' ||
         layer['source-layer'] === 'water_name')
      );
      for (const layer of waterLayers) {
        try { map.moveLayer(layer.id,beforeId); } catch (_) {}
      }
    }
  }

  function pinImage(fillColor, content='') {
    const ratio = 2;
    const width = 52 * ratio;
    const height = 58 * ratio;
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');

    const S = value => value * ratio;
    const cx = S(26);
    const cy = S(23);
    const outerR = S(19);
    const innerR = S(16);

    // Ombre douce intégrée à l'icône, sans élément HTML flottant.
    ctx.save();
    ctx.shadowColor = 'rgba(21,58,99,.23)';
    ctx.shadowBlur = S(5);
    ctx.shadowOffsetY = S(3);
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(cx, cy, outerR, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(S(18), S(35));
    ctx.lineTo(S(26), S(53));
    ctx.lineTo(S(34), S(35));
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    // Corps pastel de l'épingle.
    ctx.fillStyle = fillColor;
    ctx.beginPath();
    ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(S(21), S(34));
    ctx.lineTo(S(26), S(47));
    ctx.lineTo(S(31), S(34));
    ctx.closePath();
    ctx.fill();

    if (content) {
      ctx.font = `${S(17)}px "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(content, cx, cy + S(1));
    }

    return ctx.getImageData(0, 0, width, height);
  }

  function addPinImages() {
    const images = {
      'pt-pin-eveil': ['#4cc8c1','🎵'],
      'pt-pin-conte': ['#b8aaf1','📖'],
      'pt-pin-spectacle': ['#ff7b70','🎭'],
      'pt-pin-atelier': ['#ffd166','🥁'],
      'pt-pin-concert': ['#aad8f5','🎶'],
      'pt-pin-lecture': ['#b8aaf1','📚'],
      'pt-pin-numerique': ['#82cce8','💻'],
      'pt-pin-cinema-jeunesse': ['#d6b1e9','🎬'],
      'pt-pin-jeux': ['#b9d99b','🎲'],
      'pt-pin-cluster': ['#7fd7d1','']
    };

    for (const [name,[color,content]] of Object.entries(images)) {
      if (!map.hasImage(name)) {
        map.addImage(name,pinImage(color,content),{pixelRatio:2});
      }
    }
  }

  async function clusterExpansionZoom(clusterId) {
    const source = map.getSource('outings');
    if (!source) return null;
    try {
      return await source.getClusterExpansionZoom(Number(clusterId));
    } catch (_) {
      return null;
    }
  }

  function addOutingsSource() {
    addPinImages();

    map.addSource('outings',{
      type:'geojson',
      data:emptyCollection,
      cluster:true,
      clusterRadius:48,
      clusterMaxZoom:17
    });

    /*
      Même principe que la carte Grosses Ondes :
      les bulles sont des couches MapLibre natives, pas des Marker DOM.
      Elles sont donc dessinées dans le même repère que la carte et ne peuvent
      pas "traîner" ou se décaler pendant un zoom/déplacement.
    */
    map.addLayer({
      id:'outings-clusters',
      type:'symbol',
      source:'outings',
      filter:['has','point_count'],
      layout:{
        'icon-image':'pt-pin-cluster',
        'icon-anchor':'bottom',
        'icon-size':1,
        'icon-allow-overlap':true,
        'icon-ignore-placement':true,
        'text-field':['get','point_count_abbreviated'],
        'text-size':18,
        'text-font':['Noto Sans Bold','Noto Sans Regular'],
        'text-anchor':'center',
        'text-justify':'center',
        'text-offset':[0,-2.05],
        'text-allow-overlap':true,
        'text-ignore-placement':true
      },
      paint:{
        'text-color':'#153a63',
        'text-halo-color':'rgba(255,255,255,.70)',
        'text-halo-width':.8
      }
    });

    map.addLayer({
      id:'outings-points',
      type:'symbol',
      source:'outings',
      filter:['!', ['has','point_count']],
      layout:{
        'icon-image':[
          'match',
          ['get','category_group'],
          'eveil','pt-pin-eveil',
          'conte','pt-pin-conte',
          'atelier','pt-pin-atelier',
          'concert','pt-pin-concert',
          'lecture','pt-pin-lecture',
          'numerique','pt-pin-numerique',
          'cinema-jeunesse','pt-pin-cinema-jeunesse',
          'jeux','pt-pin-jeux',
          'pt-pin-spectacle'
        ],
        'icon-anchor':'bottom',
        'icon-size':1,
        'icon-allow-overlap':true,
        'icon-ignore-placement':true
      }
    });

    // Navigation de cluster : même logique que Grosses Ondes.
    map.on('click','outings-clusters',async event => {
      const feature = event.features?.[0];
      if (!feature) return;
      const coords = feature.geometry.coordinates.slice();
      const zoom = await clusterExpansionZoom(feature.properties?.cluster_id);
      map.easeTo({
        center:coords,
        zoom:Math.min(Number.isFinite(zoom) ? zoom : map.getZoom() + 2,16),
        duration:520
      });
    });

    map.on('click','outings-points',event => {
      const feature = event.features?.[0];
      const id = String(feature?.properties?.id || '');
      const outing = eventsById.get(id);
      if (outing) openEventPopup(outing,false);
    });

    for (const layerId of ['outings-clusters','outings-points']) {
      map.on('mouseenter',layerId,() => { map.getCanvas().style.cursor='pointer'; });
      map.on('mouseleave',layerId,() => { map.getCanvas().style.cursor=''; });
    }
  }

  function openEventPopup(event, centerMap=false) {
    if (!map || !window.maplibregl || !event || !Number.isFinite(event.lat) || !Number.isFinite(event.lng)) return;
    if (popup) popup.remove();
    popup = new window.maplibregl.Popup({
      closeButton:true,
      closeOnClick:true,
      maxWidth:'310px',
      offset:[0,-46]
    })
      .setLngLat([event.lng,event.lat])
      .setHTML(popupHtml(event))
      .addTo(map);

    if (centerMap) {
      map.easeTo({
        center:[event.lng,event.lat],
        zoom:Math.max(map.getZoom(),10),
        duration:520
      });
    }
  }

  function resetTerritoryView() {
    if (!map) return;
    if (popup) { popup.remove(); popup=null; }
    const region = territories[activeTerritory];
    // L'ancien verrou métropolitain bloque les centres ultramarins :
    // le retirer AVANT fitBounds, puis rétablir le verrou de zone.
    const previousBounds = map.getMaxBounds?.();
    map.setMaxBounds(null);
    try {
      map.fitBounds(region.view,{padding:18,duration:0,maxZoom:activeTerritory === 'metropole' ? 5.15 : 10});
      map.setMaxBounds(region.limit);
    } catch (error) {
      map.setMaxBounds(previousBounds || maxBounds);
      throw error;
    }
  }

  function setTerritory(key) {
    if (!Object.prototype.hasOwnProperty.call(territories,key)) return false;
    if (key === activeTerritory) return true;
    const previous = activeTerritory;
    activeTerritory = key;
    try {
      if (mapReady && map) resetTerritoryView();
    } catch (error) {
      activeTerritory = previous;
      if (territorySelect) territorySelect.value = previous;
      console.warn('P\u2019tites Ondes : changement de zone indisponible',error);
      return false;
    }
    if (territorySelect) territorySelect.value = key;
    render();
    return true;
  }

  function installTerritorySelect() {
    // Le module "lieux" et le moteur peuvent se charger dans un ordre different.
    // Retrouver d'abord la barre classique, puis le parent du bouton recentrer.
    const existing = document.getElementById('pt-territoires-select');
    if (existing) { territorySelect = existing; return; }
    const recenter = document.getElementById('map-recenter');
    const toolbar = document.querySelector('.outings-map-shell .map-toolbar')
      || recenter?.parentElement
      || recenter?.parentNode
      || document.querySelector('.map-toolbar');
    if (!toolbar) return;
    const label = document.createElement('label');
    label.className = 'pt-territoires-picker';
    label.htmlFor = 'pt-territoires-select';
    label.appendChild(document.createTextNode('Zone g\u00e9ographique'));
    const select = document.createElement('select');
    select.id = 'pt-territoires-select';
    select.setAttribute('aria-label','Zone g\u00e9ographique de la carte');
    for (const [key,region] of Object.entries(territories)) {
      const option = document.createElement('option');
      option.value = key;
      option.textContent = region.label;
      select.appendChild(option);
    }
    select.value = activeTerritory;
    label.appendChild(select);
    territorySelect = select;
    // Styles locaux : aucun changement CSS global du site.
    if (document.head && !document.getElementById('pt-territoires-style')) {
      const style = document.createElement('style');
      style.id = 'pt-territoires-style';
      style.textContent = '.pt-territoires-picker{display:flex;flex-direction:column;gap:3px;min-width:165px;max-width:100%;font-size:.84rem;font-weight:700;color:#21595f}' +
        '.pt-territoires-picker select{width:100%;min-width:0;min-height:38px;border:1px solid #9ac9c6;border-radius:9px;padding:6px 9px;font:inherit;background:#fff;color:#183f45;cursor:pointer}' +
        '.pt-territoires-picker select:focus-visible{outline:3px solid #0f9a91;outline-offset:2px}' +
        '@media(max-width:700px){.pt-territoires-picker{min-width:0;width:100%}}';
      document.head.appendChild(style);
    }
    if (recenter && recenter.parentNode === toolbar) toolbar.insertBefore(label,recenter);
    else toolbar.appendChild(label);
    select.addEventListener('change',() => setTerritory(select.value));
  }

  async function ensureMap() {
    if (!mapEl || mapReady) return Promise.resolve();
    if (mapInitPromise) return mapInitPromise;

    mapInitPromise = (async() => {
      try {
        const maplibregl = window.maplibregl;
        if (!maplibregl || !maplibregl.Map) throw new Error('MapLibre n’est pas chargé');

        map = new maplibregl.Map({
          container: mapEl,
          style: 'https://tiles.openfreemap.org/styles/liberty',
          center: [2.15,46.25],
          zoom: 4.45,
          minZoom: 3.6,
          maxZoom: 16,
          maxBounds,
          attributionControl: false,
          dragRotate: false,
          pitchWithRotate: false
        });

        if (map.touchZoomRotate?.disableRotation) map.touchZoomRotate.disableRotation();

        map.addControl(
          new maplibregl.NavigationControl({showCompass:false,visualizePitch:false}),
          'top-left'
        );
        map.addControl(
          new maplibregl.AttributionControl({
            compact:true,
            customAttribution:'Contours France : france-geojson · Licence Ouverte'
          }),
          'bottom-right'
        );

        await new Promise((resolve,reject) => {
          let done = false;
          const timer = setTimeout(() => {
            if (!done) reject(new Error('Délai de chargement de la carte dépassé'));
          }, 15000);

          map.once('load', () => {
            done = true;
            clearTimeout(timer);
            resolve();
          });
        });

        applyPtitesOndesVectorStyle();
        await addFranceLayer();
        addOutingsSource();

        mapReady = true;
        installTerritorySelect();
        if (activeTerritory !== 'metropole') resetTerritoryView();
        map.on('moveend',renderVisibleMapEvents);
        map.on('resize',renderVisibleMapEvents);
        updateMapData(currentFiltered,false);
        renderVisibleMapEvents();
      } catch (error) {
        console.error('P’tites Ondes: carte indisponible', error);
        try { map?.remove(); } catch (_) {}
        map = null;
        if (mapEl) mapEl.hidden = true;
        if (mapFallback) mapFallback.hidden = false;
        if (mapVisibleCount) mapVisibleCount.textContent = 'Carte indisponible';
        if (mapVisibleList) mapVisibleList.innerHTML = '';
        if (mapVisibleEmpty) mapVisibleEmpty.hidden = false;
      }
    })();

    return mapInitPromise;
  }

  function isDefaultMapView() {
    return normalize(searchInput.value) === ''
      && ageSelect.value === 'all'
      && categorySelect.value === 'all'
      && currentPeriod === 'all';
  }

  function updateMapData(filtered, fit=true) {
    if (!mapReady || !map) { ensureMap(); return; }
    const source = map.getSource('outings');
    if (!source) return;
    source.setData(toFeatureCollection(filtered));
    renderVisibleMapEvents();

    const coords = filtered.filter(e => Number.isFinite(e.lat) && Number.isFinite(e.lng)).map(e => [e.lng,e.lat]);
    if (fit) {
      if (isDefaultMapView() || coords.length === 0) {
        resetTerritoryView();
      } else if (coords.length === 1) {
        map.easeTo({center:coords[0],zoom:10,duration:450});
      } else {
        const bounds = coords.reduce((b,c) => b.extend(c),new window.maplibregl.LngLatBounds(coords[0],coords[0]));
        map.fitBounds(bounds,{padding:38,maxZoom:9,duration:480});
      }
    }
  }

  function render() {
    currentFiltered = filterEvents();
    countEl.textContent = `${currentFiltered.length} sortie${currentFiltered.length > 1 ? 's' : ''} à découvrir`;
    listEl.innerHTML = currentFiltered.map(eventCard).join('');
    emptyEl.hidden = currentFiltered.length !== 0;
    updateMapData(currentFiltered,true);
  }

  function focusEvent(id) {
    const event = eventsById.get(String(id));
    if (!event || !Number.isFinite(event.lat) || !Number.isFinite(event.lng)) return;
    const target = eventTerritory(event);
    if (target && target !== activeTerritory) setTerritory(target);
    ensureMap().then(() => {
      if (!mapReady) return;
      openEventPopup(event,true);
      mapEl.scrollIntoView({behavior:'smooth',block:'center'});
    });
  }

  if (mapVisibleList) {
    mapVisibleList.addEventListener('click', event => {
      const row = event.target.closest('[data-map-event-id]');
      if (!row) return;
      const outing = eventsById.get(String(row.dataset.mapEventId));
      if (!outing) return;
      ensureMap().then(() => {
        if (!mapReady) return;
        openEventPopup(outing,true);
      });
    });
  }

  listEl.addEventListener('click', event => {
    if (event.target.closest('a')) return;
    const card = event.target.closest('[data-event-id]');
    if (card) focusEvent(card.dataset.eventId);
  });
  listEl.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const card = event.target.closest('[data-event-id]');
    if (!card) return;
    event.preventDefault(); focusEvent(card.dataset.eventId);
  });

  [searchInput,ageSelect,categorySelect].forEach(control => control.addEventListener(control === searchInput ? 'input' : 'change',render));
  periodButtons.forEach(button => button.addEventListener('click',() => {
    currentPeriod = button.dataset.period || 'all';
    periodButtons.forEach(b => b.classList.toggle('is-active',b === button));
    render();
  }));
  resetButton.addEventListener('click',() => {
    searchInput.value=''; ageSelect.value='all'; categorySelect.value='all'; currentPeriod='all';
    periodButtons.forEach(b => b.classList.toggle('is-active',b.dataset.period === 'all'));
    if (activeTerritory !== 'metropole') { setTerritory('metropole'); }
    else render();
  });
  if (recenterButton) recenterButton.addEventListener('click',() => {
    resetTerritoryView();
    setTimeout(renderVisibleMapEvents,580);
  });

  async function load() {
    try {
      const data = typeof window.PtitesOndesLoadSorties === 'function'
        ? await window.PtitesOndesLoadSorties()
        : await (async () => {
            // En cas d'oubli du script source : retour au fonctionnement precedent.
            const response = await fetch(`config/sorties.json?v=${Date.now()}`, {cache:'no-store'});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
          })();
      events = Array.isArray(data.events) ? data.events : [];
      eventsById.clear();
      events.forEach(event => eventsById.set(String(event.id),event));
      updatedEl.textContent = formatUpdated(data.updated_at);
      currentFiltered = filterEvents();
      countEl.textContent = `${currentFiltered.length} sortie${currentFiltered.length > 1 ? 's' : ''} à découvrir`;
      listEl.innerHTML = currentFiltered.map(eventCard).join('');
      emptyEl.hidden = currentFiltered.length !== 0;
      await ensureMap();
      if (mapReady) updateMapData(currentFiltered,true);
      const hash = decodeURIComponent(location.hash.replace(/^#/,'')).trim();
      if (hash) setTimeout(() => focusEvent(hash),450);
    } catch (error) {
      console.error('P’tites Ondes: agenda indisponible',error);
      countEl.textContent='Agenda momentanément indisponible'; updatedEl.textContent='';
      listEl.innerHTML='<div class="outings-empty"><strong>Impossible de charger les sorties.</strong><span>Réessayez dans quelques instants.</span></div>';
      if (mapEl) mapEl.hidden=true;
      if (mapFallback) {mapFallback.hidden=false; mapFallback.textContent='La carte et la liste des sorties ne sont momentanément pas disponibles.';}
    }
  }

  // Un chargement differe ou une barre d'outils inseree apres le JS ne
  // doivent pas rendre le menu inexistant. Chaque installation est idempotente.
  installYouthCategoryOptions();
  installTerritorySelect();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded',installTerritorySelect,{once:true});
  }
  window.addEventListener?.('load',installTerritorySelect,{once:true});
  load();
})();
