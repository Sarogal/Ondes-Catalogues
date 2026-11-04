/* Grosses Ondes — safe, optional ticket-category rendering on the festival site.
 * Public catalogue: https://sarogal.github.io/Ondes-Catalogues/grossesondes/festivals.json
 * Requires a dedicated container and an already loaded festival object.
 * Never fetches external data, never asserts that an entire festival is sold out.
 */
(function (root) {
  "use strict";

  const STATES = Object.freeze({
    sold_out: "Épuisé",
    in_stock: "Disponible",
    limited_availability: "Places limitées",
    preorder: "Prévente",
  });
  const MAX_AGE_DAYS = 2;
  const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

  function asUtcDay(value) {
    if (typeof value !== "string" || !DATE_PATTERN.test(value)) return null;
    const [year, month, day] = value.split("-").map(Number);
    const stamp = Date.UTC(year, month - 1, day);
    if (!Number.isFinite(stamp)) return null;
    const valid = new Date(stamp).toISOString().slice(0, 10) === value;
    return valid ? stamp : null;
  }

  function parisToday() {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(new Date());
    const get = (name) => parts.find((part) => part.type === name)?.value;
    return [get("year"), get("month"), get("day")].join("-");
  }

  function safeSource(source, registered) {
    if (typeof source !== "string" || source !== registered) return false;
    try {
      const parsed = new URL(source);
      return parsed.protocol === "https:" && Boolean(parsed.hostname) &&
        !parsed.username && !parsed.password;
    } catch (_) {
      return false;
    }
  }

  function verifiedCategories(festival, today = parisToday()) {
    if (!festival || typeof festival !== "object" || Array.isArray(festival)) return null;
    const status = String(festival.status || "").toLowerCase();
    if (status.includes("annul") || status.includes("report")) return null;
    const ticket = festival.ticketAvailability;
    if (!ticket || typeof ticket !== "object" || Array.isArray(ticket)) return null;
    if (ticket.scope !== "per_category_only" ||
        !safeSource(ticket.source, festival.officialSite) ||
        !Array.isArray(ticket.categories) ||
        ticket.categories.length === 0 || ticket.categories.length > 12) return null;
    const todayStamp = asUtcDay(today);
    const verifiedStamp = asUtcDay(ticket.verifiedAt);
    if (todayStamp === null || verifiedStamp === null) return null;
    const age = (todayStamp - verifiedStamp) / 86400000;
    if (age < 0 || age > MAX_AGE_DAYS) return null;
    if (festival.endDate && asUtcDay(festival.endDate) !== null &&
        asUtcDay(festival.endDate) < todayStamp) return null;

    const seen = new Set();
    const categories = [];
    for (const entry of ticket.categories) {
      if (!entry || typeof entry !== "object" || Array.isArray(entry) ||
          typeof entry.name !== "string" || !Object.hasOwn(STATES, entry.status)) return null;
      const name = entry.name.trim().replace(/\s+/g, " ");
      if (name.length < 3 || name.length > 120) return null;
      const key = name.normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
        .replace(/[^a-z0-9]/gi, "").toLowerCase();
      if (key.length < 3 || seen.has(key)) return null;
      seen.add(key);
      categories.push({ name, status: entry.status, label: STATES[entry.status] });
    }
    return {
      source: ticket.source,
      verifiedAt: ticket.verifiedAt,
      categories,
    };
  }

  function render(container, festival, today) {
    if (!container || typeof container.replaceChildren !== "function") {
      throw new TypeError("Conteneur de billetterie absent");
    }
    const result = verifiedCategories(festival, today);
    if (!result) {
      container.replaceChildren();
      container.hidden = true;
      return false;
    }
    const doc = container.ownerDocument || root.document;
    if (!doc || typeof doc.createElement !== "function") {
      throw new TypeError("Document DOM absent");
    }
    const section = doc.createElement("section");
    section.className = "go-ticket-availability";
    const heading = doc.createElement("h4");
    heading.className = "go-ticket-availability__title";
    heading.textContent = "Billetterie — par catégorie";
    section.appendChild(heading);

    const list = doc.createElement("ul");
    list.className = "go-ticket-availability__list";
    for (const item of result.categories) {
      const li = doc.createElement("li");
      li.className = "go-ticket-availability__item";
      const label = doc.createElement("span");
      label.className = "go-ticket-availability__name";
      label.textContent = item.name;
      const state = doc.createElement("strong");
      state.className = "go-ticket-availability__status go-ticket-availability__status--" + item.status;
      state.textContent = item.label;
      li.appendChild(label);
      li.appendChild(state);
      list.appendChild(li);
    }
    section.appendChild(list);

    const note = doc.createElement("p");
    note.className = "go-ticket-availability__note";
    note.textContent = "État constaté le " +
      result.verifiedAt.split("-").reverse().join("/") +
      " ; disponibilité à confirmer auprès de la billetterie. " +
      "Une catégorie épuisée ne signifie pas que le festival est complet.";
    section.appendChild(note);
    const link = doc.createElement("a");
    link.className = "go-ticket-availability__link";
    link.href = result.source;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Vérifier sur le site officiel";
    section.appendChild(link);

    container.replaceChildren(section);
    container.hidden = false;
    return true;
  }

  root.GrossesOndesTickets = Object.freeze({
    verifiedCategories, render, parisToday,
  });
}(typeof window === "object" ? window : globalThis));
