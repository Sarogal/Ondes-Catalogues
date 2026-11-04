/* Run: node --test tests_js/test_grosses_ticket_widget.cjs */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const code = fs.readFileSync(path.resolve(
  __dirname, "../docs/grossesondes/ticket-availability.js"), "utf8");
class Node {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.textContent = "";
    this.className = "";
    this.hidden = false;
  }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
}
const root = {document: {createElement: (tag) => new Node(tag)}};
const sandbox = {window:root, URL, Date, Intl, Object, Set, Number, String};
vm.runInNewContext(code, sandbox);
const {verifiedCategories,render} = root.GrossesOndesTickets;

const ticket = {
  source:"https://festival.example.org/tickets",
  verifiedAt:"2026-11-05",
  scope:"per_category_only",
  categories:[
    {name:"Pass samedi", status:"sold_out"},
    {name:"Pass dimanche", status:"in_stock"},
  ],
};
const festival = {
  slug:"rock-metal-2027", name:"Rock Metal 2027",
  status:"Confirmé", endDate:"2027-08-22",
  officialSite:ticket.source, ticketAvailability:ticket,
};
const clone = (o) => JSON.parse(JSON.stringify(o));
const fresh = (value) => verifiedCategories(value, "2026-11-06");

test("unique official ticket categories, never a festival-wide sold-out", () => {
  const result = fresh(festival);
  assert.equal(result.categories.length, 2);
  assert.equal(result.categories[0].label, "Épuisé");
  assert.equal(result.categories[1].label, "Disponible");
  assert.equal(result.scope, undefined);
  assert.equal(result.soldOut, undefined);
});

test("age is calculated in Paris calendar days, stale and future invisible", () => {
  assert.equal(verifiedCategories(festival,"2026-11-05").categories.length,2);
  assert.equal(verifiedCategories(festival,"2026-11-07").categories.length,2);
  assert.equal(verifiedCategories(festival,"2026-11-08"),null);
  assert.equal(verifiedCategories(festival,"2026-11-04"),null);
  assert.equal(verifiedCategories(festival,"2026-02-30"),null);
  assert.match(root.GrossesOndesTickets.parisToday(), /^\d{4}-\d{2}-\d{2}$/);
});

test("source mismatch, unknown status and cancelled festival all fail closed", () => {
  for (const status of ["Annulé", "Annulée", "Reporté"]) {
    const row = clone(festival);
    row.status = status;
    assert.equal(fresh(row), null);
  }
  const bad = clone(festival);
  bad.ticketAvailability.source = "http://festival.example.org/tickets";
  assert.equal(fresh(bad), null);
  bad.ticketAvailability.source = "https://unregistered.example.org/";
  assert.equal(fresh(bad), null);
  const noScope = clone(festival);
  noScope.ticketAvailability.scope = "whole_festival";
  assert.equal(fresh(noScope), null);
  const old = clone(festival);
  old.endDate = "2026-10-01";
  assert.equal(fresh(old), null);
});

test("unknown, duplicate and malformed category availability is hidden", () => {
  const unknown = clone(festival);
  unknown.ticketAvailability.categories[0].status = "all_sold_out";
  assert.equal(fresh(unknown), null);
  const dup = clone(festival);
  dup.ticketAvailability.categories[1].name = "Pass-samedi";
  assert.equal(fresh(dup), null);
  const extra = clone(festival);
  extra.ticketAvailability.categories = Array(13).fill(
    {name:"Pass samedi",status:"sold_out"});
  assert.equal(fresh(extra), null);
  const empty = clone(festival);
  empty.ticketAvailability.categories = [];
  assert.equal(fresh(empty), null);
});

test("render uses safe DOM nodes with textContent and official URL", () => {
  const container = new Node("div");
  container.ownerDocument = root.document;
  const row = clone(festival);
  row.ticketAvailability.categories[0].name =
    '<img src=x onerror=alert(1)> Pass samedi';
  assert.equal(render(container, row, "2026-11-06"), true);
  assert.equal(container.hidden, false);
  assert.equal(container.children[0].tag, "section");
  const section = container.children[0];
  const list = section.children[1];
  assert.equal(list.children[0].children[0].textContent,
               '<img src=x onerror=alert(1)> Pass samedi');
  assert.equal(list.children[0].children.length, 2);
  const link = section.children[3];
  assert.equal(link.href, festival.officialSite);
  assert.equal(link.rel, "noopener noreferrer");
  assert.match(section.children[2].textContent,
               /Une catégorie épuisée ne signifie pas/);
});

test("expired proof removes old ticket UI from a reused festival card", () => {
  const container = new Node("div");
  assert.equal(render(container, festival, "2026-11-06"), true);
  assert.equal(render(container, festival, "2026-11-08"), false);
  assert.equal(container.children.length, 0);
  assert.equal(container.hidden, true);
});
