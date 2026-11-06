"""Read-only Pages cache diagnostic; NEVER a substitute for verify_references()."""
from hashlib import sha256
import json
from urllib.request import Request, urlopen

from official_watch import GIT, PAGES


def inspect(url, fetch=None):
    """Fetch a fixed public JSON and return bounded, public-only diagnostics."""
    if fetch is not None:
        return fetch(url)
    request = Request(url, headers={
        "User-Agent": "GrossesOndesPagesDiagnostic/1.0",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=12) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("diagnostic JSON trop volumineux")
        obj = json.loads(raw)
        headers = {k: response.headers.get(k) for k in
                   ("Age", "Cache-Control", "ETag", "Last-Modified")}
    editions = obj.get("festivals", []) if isinstance(obj, dict) else []
    noel = next((row for row in editions if isinstance(row, dict)
                 and row.get("slug") == "festival-de-noel-xxxiv-2026"), {})
    return {
        "generatedAt": obj.get("generatedAt") if isinstance(obj, dict) else None,
        "editions": len(editions),
        "noel_officialSite": noel.get("officialSite"),
        "headers": headers,
        "fingerprint": sha256(raw).hexdigest()[:12],
    }


def diagnostic(fetch=inspect):
    """Compare canonical and cache-busted reads; do not authorize ANY change."""
    results = {}
    try:
        git = fetch(GIT)
        results["git"] = git
        token = str(git.get("fingerprint", ""))[:12]
        for label, url in (
            ("pages_canonical", PAGES),
            ("pages_diagnostic_query", PAGES + "?go_probe=" + token),
        ):
            try:
                results[label] = fetch(url)
            except Exception as exc:
                results[label] = {"error": type(exc).__name__}
    except Exception as exc:
        results["error"] = type(exc).__name__
    # Print only schema-like metadata and public cache headers. Never interpret
    # query freshness as verification: watch must compare CANONICAL PAGES to GIT.
    print(json.dumps({"pages_drift_diagnostic_only": results,
                      "safe_to_publish": False},
                     ensure_ascii=False, sort_keys=True))
    return results


if __name__ == "__main__":
    diagnostic()
