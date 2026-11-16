import test from "node:test";
import assert from "node:assert/strict";
import worker, {
  MORNING_RESCUE_CRON, AFTERNOON_RESCUE_CRON, EVENING_RESCUE_CRON,
  expectedSlot, shouldDispatch,
} from "../scripts/grossesondes_concerts_external_rescue_worker.mjs";

const DAY = "2026-11-16";
const ms = (x) => Date.parse(x);
const MORNING = ms(DAY + "T07:18:00Z");
const NOW = ms(DAY + "T16:28:00Z");
const TOKEN = "TEST_TOKEN_ONLY_WITH_NO_PERMISSIONS_12345";
const run = (event, at, extra={}) => ({
  event, created_at: new Date(at).toISOString(), head_branch:"main",
  ...(event === "schedule" ? {display_title:"Concerts intake schedule=18 7 * * *"} : {}),
  ...extra,
});
const after = (slot, cron, minutes=15, extra={}) =>
  run("schedule", slot + minutes*60*1000,
      {display_title:"Concerts intake schedule=" + cron, ...extra});

test("UTC slot identity and nine-hour-ten-minute grace including previous day", () => {
  assert.equal(expectedSlot(MORNING_RESCUE_CRON, NOW), MORNING);
  assert.equal(expectedSlot(AFTERNOON_RESCUE_CRON,
      ms(DAY + "T22:21:00Z")), ms(DAY + "T13:11:00Z"));
  assert.equal(expectedSlot(EVENING_RESCUE_CRON,
      ms("2026-11-17T05:21:00Z")), ms(DAY + "T20:11:00Z"));
  assert.throws(() => expectedSlot(MORNING_RESCUE_CRON,
      ms(DAY + "T17:28:00Z")));
  assert.throws(() => expectedSlot("* * * * *", NOW));
  assert.throws(() => expectedSlot(MORNING_RESCUE_CRON, NaN));
});

test("missing slot only, no replay of successful OR failed scheduled run", () => {
  assert.equal(shouldDispatch([], MORNING, NOW), true);
  assert.equal(shouldDispatch([run("schedule", MORNING + 30*60*1000,
                                   {conclusion:"success"})], MORNING, NOW), false);
  assert.equal(shouldDispatch([run("schedule", MORNING + 60*60*1000,
                                   {conclusion:"failure"})], MORNING, NOW), false);
  assert.equal(shouldDispatch([run("workflow_dispatch", MORNING + 60*60*1000)],
                              MORNING, NOW), false);
  assert.equal(shouldDispatch([run("schedule", MORNING - 2*60*60*1000)],
                              MORNING, NOW), true);
  assert.equal(shouldDispatch([run("schedule", MORNING - 90*1000)],
                              MORNING, NOW), false);
});

test("different scheduled slots cannot hide an actually missed collection", () => {
  const afternoon = ms(DAY + "T13:11:00Z");
  const evening = ms(DAY + "T20:11:00Z");
  const afternoonRescue = ms(DAY + "T22:21:00Z");
  const eveningRescue = ms("2026-11-17T05:21:00Z");
  // The afternoon run occurs before the morning rescue, but the 07:18
  // collection is still missing. A generic event='schedule' was insufficient.
  assert.equal(shouldDispatch([
    after(afternoon,"11 13 * * *")
  ], MORNING, NOW), true);
  // Likewise, the evening run must not erase the missing afternoon slot.
  assert.equal(shouldDispatch([
    after(evening,"11 20 * * *")
  ], afternoon, afternoonRescue), true);
  // A genuine delayed morning run remains attributed to morning even if
  // it starts after the next cron's normal wall-clock time.
  assert.equal(shouldDispatch([
    after(MORNING,"18 7 * * *",7*60)
  ], MORNING, NOW), false);
  // Independent slots can coexist: no replay of a known failed morning.
  assert.equal(shouldDispatch([
    after(MORNING,"18 7 * * *",3*60,{conclusion:"failure"}),
    after(afternoon,"11 13 * * *")
  ], MORNING, NOW), false);
  assert.equal(shouldDispatch([
    after(evening,"11 20 * * *")
  ], evening, eveningRescue), false);
});

test("unlabelled legacy and forged schedule titles fail closed", () => {
  const afternoon = ms(DAY + "T13:11:00Z");
  assert.throws(() => shouldDispatch([
    after(afternoon,"11 13,20 * * *")
  ], MORNING, NOW), /cannot be authenticated/);
  assert.throws(() => shouldDispatch([
    run("schedule",MORNING+120000,{display_title:""})
  ], MORNING, NOW), /cannot be authenticated/);
  assert.throws(() => shouldDispatch([
    after(MORNING,"11 13 * * *")
  ], MORNING, NOW + 1000), /cannot be authenticated/);
  assert.throws(() => shouldDispatch([], ms(DAY + "T08:00:00Z"), NOW),
                /Unknown original GitHub concert slot/);
});

test("malformed, truncated, or premature API observation fails closed", () => {
  assert.throws(() => shouldDispatch([], MORNING, MORNING + 8*60*60*1000));
  assert.throws(() => shouldDispatch(new Array(100).fill(run("schedule", MORNING)),
                                     MORNING, NOW));
  assert.throws(() => shouldDispatch([{}], MORNING, NOW));
  assert.throws(() => shouldDispatch([run("schedule", MORNING,
                                         {created_at:"not-a-date"})], MORNING, NOW));
});

test("HTTP endpoint inert and bad cron/token cannot dispatch", async () => {
  assert.equal((await worker.fetch()).status, 404);
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {calls++; throw new Error("no network permitted");};
  try {
    await assert.rejects(worker.scheduled(
      {cron:"* * * * *",scheduledTime:NOW},{GITHUB_DISPATCH_TOKEN:TOKEN}));
    await assert.rejects(worker.scheduled(
      {cron:MORNING_RESCUE_CRON,scheduledTime:NOW},{}));
    await assert.rejects(worker.scheduled(
      {cron:MORNING_RESCUE_CRON,scheduledTime:NOW},
      {GITHUB_DISPATCH_TOKEN:"  " + TOKEN + " "}));
  } finally {
    globalThis.fetch=original;
  }
  assert.equal(calls,0);
});

test("no action when scheduled or manual run already exists, even if failed", async () => {
  const original=globalThis.fetch, originalNow=Date.now;
  const calls=[];
  globalThis.fetch=async (url,options)=>{
    calls.push({url,options});
    return {status:200, json:async()=>({workflow_runs:[
      run("schedule", MORNING + 45*60*1000,{conclusion:"failure"})
    ]})};
  };
  Date.now=()=>NOW;
  try {
    await worker.scheduled({cron:MORNING_RESCUE_CRON,scheduledTime:NOW},
                           {GITHUB_DISPATCH_TOKEN:TOKEN});
  } finally {
    globalThis.fetch=original; Date.now=originalNow;
  }
  assert.equal(calls.length,1);
  assert.equal(calls[0].options.method,"GET");
});

test("exactly one safe dispatch after truly absent slot, never to private repo", async () => {
  const original=globalThis.fetch, originalNow=Date.now;
  const calls=[];
  globalThis.fetch=async (url,options)=>{
    calls.push({url,options});
    return options.method==="GET" ?
      {status:200,json:async()=>({workflow_runs:[
        run("schedule", MORNING - 11*60*60*1000)
      ]})} : {status:204};
  };
  Date.now=()=>NOW;
  try {
    await worker.scheduled({cron:MORNING_RESCUE_CRON,scheduledTime:NOW},
                           {GITHUB_DISPATCH_TOKEN:TOKEN});
  } finally {
    globalThis.fetch=original; Date.now=originalNow;
  }
  assert.equal(calls.length,2);
  assert.match(calls[0].url,/Ondes-Catalogues\/actions\/workflows\/grossesondes-concerts-private-intake/);
  assert.equal(calls[1].options.method,"POST");
  assert.match(calls[1].url,/Ondes-Catalogues\/actions\/workflows\/grossesondes-concerts-private-intake/);
  assert.deepEqual(JSON.parse(calls[1].options.body),{
    ref:"main",inputs:{phase:"catchup"},
  });
  assert.equal(calls[1].options.headers.Authorization,"Bearer "+TOKEN);
  assert.doesNotMatch(calls.map(c=>c.url+" "+(c.options.body||"")).join("\n"),
                      /GrossesOndes|TEST_TOKEN|approved\.json/);
});

test("GitHub metadata denial or malformed JSON does not trigger dispatch", async () => {
  const original=globalThis.fetch, originalNow=Date.now;
  let calls=0;
  Date.now=()=>NOW;
  try {
    for(const response of [
      {status:403}, {status:200,json:async()=>({workflow_runs:null})},
      {status:200,json:async()=>({workflow_runs:[{bad:"object"}]})},
    ]){
      calls=0;
      globalThis.fetch=async ()=>{calls++; return response;};
      await assert.rejects(worker.scheduled(
        {cron:MORNING_RESCUE_CRON,scheduledTime:NOW},
        {GITHUB_DISPATCH_TOKEN:TOKEN}));
      assert.equal(calls,1);
    }
  } finally {
    globalThis.fetch=original; Date.now=originalNow;
  }
});

test("GitHub dispatch failure never leaks token or response body", async () => {
  const original=globalThis.fetch, originalNow=Date.now;
  globalThis.fetch=async (_,options)=> options.method==="GET" ?
    {status:200,json:async()=>({workflow_runs:[]})} :
    {status:403,text:async()=>TOKEN};
  Date.now=()=>NOW;
  try {
    await assert.rejects(worker.scheduled(
      {cron:MORNING_RESCUE_CRON,scheduledTime:NOW},
      {GITHUB_DISPATCH_TOKEN:TOKEN}),error=>
        error.message==="GitHub dispatch HTTP 403" &&
        !error.message.includes(TOKEN));
  } finally {
    globalThis.fetch=original;Date.now=originalNow;
  }
});
