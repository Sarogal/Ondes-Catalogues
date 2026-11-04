/* Grosses Ondes — pont artistes entre les festivals et les concerts.
 * Aucune date inventée : sans lineupByDate, le jour de passage reste inconnu.
 * Chargement à la demande, noms rapprochés par égalité canonique/alias uniquement.
 */
(function (root) {
  'use strict';
  const BASE = 'https://sarogal.github.io/Ondes-Catalogues/grossesondes/';
  const FESTIVALS = BASE + 'festivals.json';
  const CONCERTS = BASE + 'concerts.json';
  const norm = value => String(value || '').normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
    .replace(/\s+/g, ' ');
  const isIso = x => typeof x === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(x) &&
    !Number.isNaN(new Date(x + 'T12:00:00Z').valueOf()) &&
    new Date(x + 'T12:00:00Z').toISOString().slice(0, 10) === x;
  const unique = a => [...new Set(a.filter(Boolean))];
  function artistIdentity(name, artists) {
    const key = norm(name);
    if (!key) return {artist: null, ambiguous: false, aliases: []};
    const found = (Array.isArray(artists) ? artists : []).filter(a =>
      a && [a.name, ...(Array.isArray(a.aliases) ? a.aliases : [])].some(n => norm(n) === key));
    if (found.length !== 1) return {artist: null, ambiguous: found.length > 1, aliases: [name]};
    return {artist: found[0], ambiguous: false,
      aliases: unique([name, found[0].name, ...(found[0].aliases || [])])};
  }
  const HISTORY = BASE + 'festival-history.json';
  const archiveTitle = f => norm(f.name).replace(/^festival /, '')
    .replace(/\\b20[2-4][0-9]\\b/g, '').replace(/ (?:i|ii|iii|iv|v|vi|vii|viii|ix|x|[0-9]+)$/, '').trim();
  function documentedArchive(f, today) {
    if (!f || !Array.isArray(f.lineup) || !f.lineup.length ||
        !isIso(f.startDate) || !isIso(f.endDate) || f.startDate > f.endDate ||
        f.endDate >= today || Number(f.startDate.slice(0, 4)) !== f.lastKnownYear) return false;
    const proof = norm(f.verificationStatus || '');
    const confirmed = /document|controle|confirm|officiel|attest|edition tenue|reellement tenue|effectivement tenue|compte rendu/.test(proof);
    const caution = /non confirm|non recoup|a recoup|a corrobor|non prouv|a verifier|non attest|incertain|hypothetique|annul|non certifi|a etablir|non audite/.test(proof);
    return confirmed && !caution && Boolean(safeHttps(f.source) || safeHttps(f.officialSite));
  }
  function identicalEdition(history, live) {
    if (history.startDate !== live.startDate || history.endDate !== live.endDate ||
        norm(history.city) !== norm(live.city)) return false;
    const slug = String(history.slug || '');
    const sameSlug = Boolean(slug && (live.slug === slug || String(live.slug || '').startsWith(slug + '-')));
    const source = safeHttps(history.source || history.officialSite);
    const liveSource = safeHttps(live.source || live.officialSite);
    return sameSlug || archiveTitle(history) === archiveTitle(live) ||
      Boolean(source && source === liveSource);
  }
  function collectAppearances(name, festivalDoc, concertDoc, historyDoc, asOf) {
    const artists = concertDoc && Array.isArray(concertDoc.artists) ? concertDoc.artists : [];
    const id = artistIdentity(name, artists);
    const keys = new Set((id.aliases.length ? id.aliases : [name]).map(norm));
    const venues = new Map(((concertDoc && concertDoc.venues) || []).map(v => [v.id, v]));
    const concerts = [];
    if (id.artist && Array.isArray(concertDoc.events)) {
      for (const event of concertDoc.events) {
        if (!Array.isArray(event.artistIds) || !event.artistIds.includes(id.artist.id)) continue;
        const venue = venues.get(event.venueId);
        if (!venue || !isIso(event.date)) continue;
        concerts.push({
          type: 'concert', key: 'c:' + event.id, title: event.title,
          date: event.date, end: event.date, exact: true,
          place: [venue.name, venue.city].filter(Boolean).join(' · '),
          city: venue.city || '', status: event.status || '',
          source: event.officialUrl || '', lastVerified: event.lastVerified || ''
        });
      }
    }
    const festivals = [];
    for (const f of (festivalDoc && Array.isArray(festivalDoc.festivals) ? festivalDoc.festivals : [])) {
      if (!f || !f.slug || !f.name) continue;
      const byDate = f.lineupByDate && typeof f.lineupByDate === 'object' &&
        !Array.isArray(f.lineupByDate) ? f.lineupByDate : {};
      const precise = Object.keys(byDate).filter(date =>
        isIso(date) && Array.isArray(byDate[date]) &&
        byDate[date].some(n => keys.has(norm(n))));
      const onPoster = Array.isArray(f.lineup) && f.lineup.some(n => keys.has(norm(n)));
      if (!onPoster && !precise.length) continue;
      if (precise.length) {
        for (const date of unique(precise)) festivals.push({
          type: 'festival', key: 'f:' + f.slug + ':' + date, title: f.name,
          date, end: date, exact: true, city: f.city || '', place: f.city || '',
          status: f.status || '', source: f.officialSite || f.source || '',
          slug: f.slug, lastVerified: f.lastVerified || ''
        });
      } else {
        festivals.push({
          type: 'festival', key: 'f:' + f.slug, title: f.name,
          date: isIso(f.startDate) ? f.startDate : null,
          end: isIso(f.endDate) ? f.endDate : null,
          exact: false, city: f.city || '', place: f.city || '',
          status: f.status || '', source: f.officialSite || f.source || '',
          slug: f.slug, lastVerified: f.lastVerified || ''
        });
      }
    }
    const historyRows = historyDoc && historyDoc.schema === 2 &&
      Array.isArray(historyDoc.knownFestivals) ? historyDoc.knownFestivals : [];
    const referenceDay = isIso(asOf) ? asOf : parisDay();
    const published = festivalDoc && Array.isArray(festivalDoc.festivals) ? festivalDoc.festivals : [];
    for (const h of historyRows) {
      if (!documentedArchive(h, referenceDay) ||
          !h.lineup.some(n => keys.has(norm(n))) ||
          published.some(f => identicalEdition(h, f))) continue;
      const source = safeHttps(h.source) || safeHttps(h.officialSite);
      const dates = h.lineupByDate && typeof h.lineupByDate === 'object' &&
        !Array.isArray(h.lineupByDate) ?
        Object.keys(h.lineupByDate).filter(date => isIso(date) &&
          date >= h.startDate && date <= h.endDate &&
          Array.isArray(h.lineupByDate[date]) &&
          h.lineupByDate[date].some(n => keys.has(norm(n)))) : [];
      const validDays = dates.length ? unique(dates) : [null];
      for (const day of validDays) festivals.push({
        type: 'festival', historical: true,
        key: 'h:' + (h.slug || norm(h.name)) + ':' + h.startDate + (day ? ':' + day : ''),
        title: h.name, date: day || h.startDate, end: day || h.endDate,
        exact: Boolean(day), city: h.city || '', place: h.city || '',
        status: 'Archive documentée', source, slug: h.slug,
        lastVerified: h.lastVerified || ''
      });
    }
    const sort = (a, b) => (a.date || '9999').localeCompare(b.date || '9999') ||
      a.type.localeCompare(b.type) || a.title.localeCompare(b.title, 'fr');
    return {name: id.artist ? id.artist.name : name, ambiguous: id.ambiguous,
      concerts: concerts.sort(sort), festivals: festivals.sort(sort),
      all: [...concerts, ...festivals].sort(sort)};
  }
  function parisDay() {
    const parts = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(new Date());
    const get = k => parts.find(x => x.type === k).value;
    return get('year') + '-' + get('month') + '-' + get('day');
  }
  const isUnavailableStatus = status =>
    /annul|report|cancel|postpon|reprogram|reschedul/i.test(String(status || ''));
  function statusLabel(raw) {
    const value = String(raw || '').trim();
    const labels = {confirmed: 'Confirmé', announced: 'Annoncé',
      cancelled: 'Annulé', postponed: 'Reporté', rescheduled: 'Reprogrammé'};
    return labels[value.toLowerCase()] || value;
  }
  function classify(rows, today) {
    const upcoming = [], past = [], unavailable = [];
    for (const row of rows) {
      if (isUnavailableStatus(row.status)) unavailable.push(row);
      else if (!row.date || (row.end || row.date) >= today) upcoming.push(row);
      else past.push(row);
    }
    return {upcoming, past, unavailable};
  }
  function safeHttps(raw) {
    try {
      const u = new URL(String(raw || ''));
      return u.protocol === 'https:' && u.hostname && !u.username && !u.password ? u.href : '';
    } catch (_) { return ''; }
  }
  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = String(text);
    return el;
  }
  function formatDate(date) {
    if (!isIso(date)) return 'Date à confirmer';
    return new Intl.DateTimeFormat('fr-FR', {
      day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'
    }).format(new Date(date + 'T12:00:00Z'));
  }
  function presentDate(row) {
    if (row.exact) return formatDate(row.date);
    if (!row.date) return 'Date du festival à confirmer · jour de passage inconnu';
    if (!row.end || row.end === row.date)
      return 'Festival le ' + formatDate(row.date) + ' · jour de passage non précisé';
    return 'Festival du ' + formatDate(row.date) + ' au ' + formatDate(row.end) +
      ' · jour de passage non précisé';
  }
  function link(label, url) {
    const href = safeHttps(url);
    if (!href) return null;
    const a = node('a', 'go-artist-dates__source', label);
    a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
    return a;
  }
  function rowNode(row) {
    const item = node('li', 'go-artist-dates__item');
    const meta = node('div', 'go-artist-dates__type', row.type === 'concert' ? 'CONCERT' :
      (row.historical ? 'FESTIVAL · ARCHIVE' : 'FESTIVAL'));
    const title = node('strong', '', row.title || 'Événement');
    const date = node('p', 'go-artist-dates__date', presentDate(row));
    const place = node('p', 'go-artist-dates__place', row.place || 'Lieu à préciser');
    item.append(meta, title, date, place);
    if (row.status) {
      item.append(node('p', isUnavailableStatus(row.status) ?
        'go-artist-dates__warning' : 'go-artist-dates__status',
        'Statut : ' + statusLabel(row.status)));
    }
    const official = link(row.historical ? 'Consulter la source de l’archive' :
      'Vérifier la source officielle', row.source);
    if (official) item.append(official);
    return item;
  }
  function section(title, rows) {
    const wrapper = node('section', 'go-artist-dates__section');
    wrapper.append(node('h3', '', title + ' (' + rows.length + ')'));
    if (!rows.length) wrapper.append(node('p', 'go-artist-dates__empty', 'Aucune date référencée dans cette catégorie.'));
    else {
      const list = node('ul', 'go-artist-dates__list');
      for (const row of rows) list.append(rowNode(row));
      wrapper.append(list);
    }
    return wrapper;
  }
  async function load(url, valid) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (!valid(data)) throw new Error('Catalogue de format inattendu');
      return data;
    } finally { clearTimeout(timeout); }
  }
  let active = null;
  function open(name, fallbackFestivals) {
    const label = String(name || '').trim();
    if (!label) return;
    if (active) active.close();
    const previousFocus = document.activeElement;
    const priorOverflow = document.body.style.overflow;
    const backdrop = node('div', 'go-artist-dates__backdrop');
    const dialog = node('section', 'go-artist-dates__dialog');
    dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-label', 'Dates du groupe ' + label);
    const header = node('div', 'go-artist-dates__header');
    const heading = node('h2', '', 'Toutes les dates de ' + label);
    const closeButton = node('button', 'go-artist-dates__close', 'Fermer ×');
    closeButton.type = 'button';
    header.append(heading, closeButton);
    const body = node('div', 'go-artist-dates__body');
    body.append(node('p', '', 'Concerts et festivals en France référencés par Grosses Ondes. Les absences ne prouvent pas qu’un groupe n’a pas d’autres dates.'));
    const loading = node('p', 'go-artist-dates__loading', 'Recherche dans les deux catalogues…');
    body.append(loading); dialog.append(header, body); backdrop.append(dialog);
    let closed = false;
    const close = () => {
      if (closed) return;
      closed = true; backdrop.remove();
      document.removeEventListener('keydown', onKey, true);
      document.body.style.overflow = priorOverflow;
      if (active && active.close === close) active = null;
      if (previousFocus && previousFocus.isConnected && previousFocus.focus) previousFocus.focus();
    };
    const onKey = e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); close(); return; }
      if (e.key !== 'Tab') return;
      const choices = [...backdrop.querySelectorAll('button, a[href]')];
      if (!choices.length) return;
      const first = choices[0], last = choices[choices.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    closeButton.addEventListener('click', close);
    backdrop.addEventListener('click', e => {if (e.target === backdrop) close();});
    document.addEventListener('keydown', onKey, true);
    document.body.append(backdrop); document.body.style.overflow = 'hidden';
    closeButton.focus();
    active = {close};
    (async () => {
      const results = await Promise.allSettled([
        load(FESTIVALS, x => x && x.schema === 1 && Array.isArray(x.festivals) && x.festivals.length > 0),
        load(CONCERTS, x => x && x.schemaVersion === 1 &&
          Array.isArray(x.events) && Array.isArray(x.artists) && Array.isArray(x.venues)),
        load(HISTORY, x => x && x.schema === 2 && Array.isArray(x.knownFestivals))
      ]);
      if (closed) return;
      const festivalOk = results[0].status === 'fulfilled';
      const concertOk = results[1].status === 'fulfilled';
      const fallback = Array.isArray(fallbackFestivals) ? fallbackFestivals : [];
      const f = festivalOk ? results[0].value : {festivals: fallback};
      const c = concertOk ? results[1].value : {artists: [], venues: [], events: []};
      const historyOk = results[2].status === 'fulfilled';
      const h = historyOk ? results[2].value : {knownFestivals: []};
      const found = collectAppearances(label, f, c, h, parisDay());
      const grouped = classify(found.all, parisDay());
      loading.remove();
      if (!festivalOk || !concertOk || !historyOk) {
        body.append(node('p', 'go-artist-dates__warning',
          'Résultats partiels : ' + [
            !festivalOk ? 'catalogue Festivals indisponible' : '',
            !concertOk ? 'catalogue Concerts indisponible' : '',
            !historyOk ? 'archives Festivals indisponibles' : ''
          ].filter(Boolean).join(' ; ') + '.'));
      }
      if (found.ambiguous) body.append(node('p', 'go-artist-dates__warning',
        'Nom partagé par plusieurs artistes : correspondance des concerts suspendue pour éviter les confusions.'));
      body.append(node('p', 'go-artist-dates__count',
        found.concerts.length + ' concert(s) et ' + found.festivals.length +
        ' apparition(s) en festival référencés.'));
      body.append(section('Dates à venir ou à préciser', grouped.upcoming));
      if (grouped.unavailable.length) body.append(section('Dates annulées ou reportées', grouped.unavailable));
      if (grouped.past.length) body.append(section('Dates passées — archives',
        [...grouped.past].sort((a, b) => (b.date || '').localeCompare(a.date || ''))));
      if (!found.all.length && festivalOk && concertOk) body.append(node('p', '',
        'Aucune autre date nominative répertoriée à ce jour.'));
    })().catch(() => {
      if (!closed) loading.textContent = 'Impossible de charger les dates actuellement. Réessayez plus tard.';
    });
  }
  const api = Object.freeze({open, collectAppearances, artistIdentity,
    classify, isUnavailableStatus, statusLabel, norm, isIso, safeHttps});
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.GrossesOndesArtists = api;
}(typeof window === 'object' ? window : globalThis));
