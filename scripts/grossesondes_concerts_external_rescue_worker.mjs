// Cloudflare Free: read-only GitHub schedule check plus tightly-scoped rescue.
// Not deployed: the owner must separately enable an independent Worker cron.
// No private repo API, sensitive candidate records, or HTTP dispatch endpoint.
export const MORNING_RESCUE_CRON = "28 16 * * *";
export const AFTERNOON_RESCUE_CRON = "21 22 * * *";
export const EVENING_RESCUE_CRON = "21 05 * * *";
export const RESCUE_SLOTS = Object.freeze({
  [MORNING_RESCUE_CRON]: {h: 7, m: 18, sourceCron: "18 7 * * *", previousDay: false, runH: 16, runM: 28},
  [AFTERNOON_RESCUE_CRON]: {h: 13, m: 11, sourceCron: "11 13 * * *", previousDay: false, runH: 22, runM: 21},
  [EVENING_RESCUE_CRON]: {h: 20, m: 11, sourceCron: "11 20 * * *", previousDay: true, runH: 5, runM: 21},
});
const API = "https://api.github.com/repos/Sarogal/Ondes-Catalogues/actions/workflows/";
const WORKFLOW = "grossesondes-concerts-private-intake-on-public-runners.yml";
const WINDOW_BEFORE = 2 * 60 * 1000;
const WINDOW_AFTER = 9 * 60 * 60 * 1000;

export function expectedSlot(cron, scheduledTime) {
  const config = RESCUE_SLOTS[cron];
  if (!config || !Number.isFinite(scheduledTime)) {
    throw new Error("Unknown concert rescue cron or clock");
  }
  const at = new Date(scheduledTime);
  if (at.getUTCHours() !== config.runH || at.getUTCMinutes() !== config.runM) {
    throw new Error("Cron and scheduled UTC instant disagree");
  }
  let target = Date.UTC(at.getUTCFullYear(), at.getUTCMonth(), at.getUTCDate(),
                        config.h, config.m);
  if (config.previousDay) target -= 24 * 60 * 60 * 1000;
  if (scheduledTime - target !== (9 * 60 + 10) * 60 * 1000) {
    throw new Error("Rescue must run nine hours and ten minutes after slot");
  }
  return target;
}

export function shouldDispatch(runs, slot, checkedAt) {
  if (!Array.isArray(runs) || runs.length >= 100 ||
      !Number.isFinite(slot) || !Number.isFinite(checkedAt) ||
      checkedAt < slot + WINDOW_AFTER) {
    throw new Error("Unverifiable run history or premature rescue");
  }
  // All three cron expressions are distinct on the trusted main workflow.
  // GitHub may start a different slot before a 9h10 rescue window closes.
  // Never mistake that later run for evidence that THIS slot happened.
  const utc = new Date(slot);
  const trigger = Object.values(RESCUE_SLOTS).find(config =>
    config.h === utc.getUTCHours() && config.m === utc.getUTCMinutes());
  if (!trigger) throw new Error("Unknown original GitHub concert slot");
  const title = "Concerts intake schedule=" + trigger.sourceCron;
  const knownTitles = Object.values(RESCUE_SLOTS).map(config =>
    "Concerts intake schedule=" + config.sourceCron);
  for (const item of runs) {
    if (!item || typeof item !== "object" ||
        typeof item.event !== "string" ||
        typeof item.created_at !== "string") {
      throw new Error("Malformed GitHub workflow run metadata");
    }
    const at = Date.parse(item.created_at);
    if (!Number.isFinite(at)) {
      throw new Error("Invalid GitHub run creation time");
    }
    // A scheduled run counts even if its secure publisher held a candidate.
    // Do not repeat known refusals or start overlapping collection runs.
    if (item.event === "schedule" &&
        at >= slot - WINDOW_BEFORE && at <= checkedAt) {
      // Old unlabelled or mismatched runs cannot be safely attributed:
      // fail closed, never trigger a second private proof evaluation.
      if (!knownTitles.includes(item.display_title)) {
        throw new Error("Scheduled run slot cannot be authenticated");
      }
      if (item.display_title === title) return false;
    }
    if (item.event === "workflow_dispatch" &&
        at >= slot && at <= checkedAt && item.head_branch === "main") {
      return false;
    }
  }
  return true;
}

export default {
  async fetch() {
    // A public HTTP request cannot initiate a credentialed dispatch.
    return new Response("Not found", {status: 404});
  },
  async scheduled(controller, env) {
    const slot = expectedSlot(controller?.cron, controller?.scheduledTime);
    const token = env?.GITHUB_DISPATCH_TOKEN;
    if (typeof token !== "string" || token.length < 20 ||
        token.trim() !== token) {
      throw new Error("Scoped GitHub token missing or malformed");
    }
    const headers = {
      Authorization: "Bearer " + token,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "grossesondes-independent-concerts-rescue",
    };
    const response = await fetch(API + WORKFLOW + "/runs?per_page=100", {
      method: "GET", headers,
    });
    if (response.status !== 200) {
      throw new Error("GitHub workflow metadata HTTP " + response.status);
    }
    // Never interpret partial/malformed GitHub API output as a missed run.
    const data = await response.json();
    if (!data || !Array.isArray(data.workflow_runs)) {
      throw new Error("GitHub returned no authoritative workflow run list");
    }
    if (!shouldDispatch(data.workflow_runs, slot, Date.now())) {
      console.log("Concerts rescue not required: workflow already launched");
      return;
    }
    const result = await fetch(API + WORKFLOW + "/dispatches", {
      method: "POST",
      headers: {...headers, "Content-Type": "application/json"},
      body: JSON.stringify({ref: "main", inputs: {phase: "catchup"}}),
    });
    if (result.status !== 204) {
      throw new Error("GitHub dispatch HTTP " + result.status);
    }
    // 204 means request accepted, not that a safe concert was published.
    console.log("Concerts scheduled gap: one public-runner catchup requested");
  },
};
