"""GitHub Actions: audit privé sans modifier ni le patch, ni le JSON public."""
from datetime import datetime
import json
import os
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from private_intake import github, PATH, BRANCH
from outings_promotion import preview

CATALOG = Path("docs/ptitesondes/sorties.json")
REPORT = Path("/tmp/ptitesondes-promotion-preview.json")


def main():
    token = os.getenv("PRIVATE_INTAKE_READ_TOKEN")
    if not token:
        raise RuntimeError("Token GitHub privé lecture seule absent")
    suffix = "?ref=" + quote(BRANCH, safe="")
    response = github(quote(PATH + "/backlog.json", safe="/") + suffix, token)
    import base64
    if response.get("encoding") != "base64":
        raise ValueError("Backlog GitHub non décodable")
    raw = base64.b64decode(response.get("content", ""), validate=True)
    if len(raw) > 1_000_000:
        raise ValueError("Backlog trop volumineux")
    leads = json.loads(raw)
    public = json.loads(CATALOG.read_text(encoding="utf-8"))
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    assessment = preview(leads, public, today)
    # Aucune fiche détaillée dans les logs ou dans le résumé, uniquement les comptes.
    report = {
        "day": today.isoformat(),
        "backlog_size": len(leads),
        "examined_registered_venues": assessment["examined"],
        "official_index_requests": assessment["network_requests"],
        "fully_verified_candidates": len(assessment["accepted"]),
        "reasons": assessment["rejected_by_reason"],
        "public_changes": 0,
        "mode": assessment["mode"],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
