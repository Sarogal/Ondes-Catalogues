// Cloudflare Workers Free: independent, credential-scoped GitHub rescue.
// This module is intentionally HTTP-inert: only a Cloudflare Cron Trigger
// can initiate a workflow. Never log or include a GitHub token in a URL.
export const OUTINGS_CRON = "47 7,10,14,18 * * *";
export const PLACES_CRON = "57 21 * * *";
const DISPATCH_ENDPOINT =
  "https://api.github.com/repos/Sarogal/Ondes-Catalogues/actions/workflows/" +
  "ptitesondes-private-intake-on-public-runners.yml/dispatches";

export default {
  async fetch() {
    return new Response("Not found", { status: 404 });
  },
  async scheduled(controller, env) {
    if (controller?.cron !== OUTINGS_CRON && controller?.cron !== PLACES_CRON) {
      throw new Error("Unsupported independent cron");
    }
    const token = env?.GITHUB_DISPATCH_TOKEN;
    if (typeof token !== "string" || token.length < 20 || token.trim() !== token) {
      throw new Error("GitHub dispatch secret is missing or malformed");
    }
    const outings = controller.cron === OUTINGS_CRON;
    const inputs = {
      cycle: outings ? "outings" : "places",
      mode: "write",
      recovery: outings ? "catchup" : "none",
    };
    const response = await fetch(DISPATCH_ENDPOINT, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ptitesondes-independent-rescue",
      },
      body: JSON.stringify({ ref: "main", inputs }),
    });
    if (response.status !== 204) {
      // Never dump response headers/body; they can contain operational details.
      throw new Error(`GitHub dispatch HTTP ${response.status}`);
    }
    console.log(`GitHub rescue dispatched: ${inputs.cycle}`);
  },
};
