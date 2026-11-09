import test from "node:test";
import assert from "node:assert/strict";
import worker, {OUTINGS_CRON, PLACES_CRON} from "../scripts/ptitesondes_external_rescue_worker.mjs";

test("HTTP surface is inert even with a configured secret", async () => {
  const response = await worker.fetch(new Request("https://example.workers.dev/"));
  assert.equal(response.status, 404);
});

test("both cron routes dispatch to exactly one public workflow and no private permissions", async () => {
  const old = globalThis.fetch;
  const received = [];
  const secret = "TEST_TOKEN_NOT_REAL_123456789";
  globalThis.fetch = async (url, options) => {
    received.push({url, options});
    return {status: 204};
  };
  try {
    await worker.scheduled({cron: OUTINGS_CRON}, {GITHUB_DISPATCH_TOKEN: secret});
    await worker.scheduled({cron: PLACES_CRON}, {GITHUB_DISPATCH_TOKEN: secret});
  } finally {
    globalThis.fetch = old;
  }
  assert.equal(received.length, 2);
  for (const item of received) {
    assert.match(item.url, /^https:\/\/api\.github\.com\/repos\/Sarogal\/Ondes-Catalogues\/actions\/workflows\//);
    assert.equal(item.options.method, "POST");
    assert.equal(item.options.headers.Authorization, `Bearer ${secret}`);
    assert.equal(JSON.parse(item.options.body).ref, "main");
    assert.doesNotMatch(item.url + item.options.body, /PtitesOndes|TEST_TOKEN/);
  }
  assert.deepEqual(JSON.parse(received[0].options.body).inputs, {cycle:"outings",mode:"write",recovery:"catchup"});
  assert.deepEqual(JSON.parse(received[1].options.body).inputs, {cycle:"places",mode:"write",recovery:"none"});
});

test("unknown cron or absent token cannot dispatch", async () => {
  const old = globalThis.fetch;
  let called = 0;
  globalThis.fetch = async () => {called++; return {status: 204};};
  try {
    await assert.rejects(worker.scheduled({cron:"* * * * *"}, {GITHUB_DISPATCH_TOKEN:"TEST_TOKEN_NOT_REAL_123456789"}));
    await assert.rejects(worker.scheduled({cron:OUTINGS_CRON}, {}));
    await assert.rejects(worker.scheduled({cron:OUTINGS_CRON}, {GITHUB_DISPATCH_TOKEN:"  TEST_TOKEN_NOT_REAL_123456789 "}));
  } finally {
    globalThis.fetch = old;
  }
  assert.equal(called, 0);
});

test("GitHub API failure is recorded without leaking secret or response", async () => {
  const old = globalThis.fetch;
  globalThis.fetch = async () => ({status: 403, text: async () => "test secret leaked"});
  try {
    await assert.rejects(
      worker.scheduled({cron:OUTINGS_CRON}, {GITHUB_DISPATCH_TOKEN:"TEST_TOKEN_NOT_REAL_123456789"}),
      error => error.message === "GitHub dispatch HTTP 403"
    );
  } finally {
    globalThis.fetch = old;
  }
});
