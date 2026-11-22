"""Local PRIVATE-only OpenAgenda institutional registry coverage CLI.

Run on a trusted private worker. stdout contains ONLY fixed-schema aggregates,
never titles, URLs, event UIDs, candidate identifiers or source records.
No HTTP, GitHub API, credentials, publishing or filesystem writes.
"""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

from ptitesondes_openagenda_v2_institutional_delegation import (
    census_institution_pins_on_private_backlog,
)

MAX_BACKLOG_BYTES = 2_000_000
MAX_REGISTRY_BYTES = 200_000


def _read(path, max_bytes):
    p = Path(path)
    if not p.is_file() or p.stat().st_size > max_bytes:
        raise ValueError("invalid_private_file")
    raw = p.read_bytes()
    if len(raw) > max_bytes:
        raise ValueError("invalid_private_file")
    return json.loads(raw.decode("utf-8"))


def run(backlog_path, source_registry_path, day):
    """Pure report result after bounded file reads, no write paths."""
    if not isinstance(day, str):
        raise ValueError("invalid_day")
    today = date.fromisoformat(day)
    if today.isoformat() != day:
        raise ValueError("invalid_day")
    backlog = _read(backlog_path, MAX_BACKLOG_BYTES)
    # No independently reviewed register is a legitimate inventory baseline.
    # This NEVER promotes candidate metadata into an approved source.
    sources = ([] if source_registry_path is None else
               _read(source_registry_path, MAX_REGISTRY_BYTES))
    return census_institution_pins_on_private_backlog(backlog, sources, today)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-backlog", required=True)
    parser.add_argument("--independently-curated-registry")
    parser.add_argument("--today", required=True)
    args = parser.parse_args(argv)
    try:
        summary = run(
            args.private_backlog, args.independently_curated_registry,
            args.today)
    except (ValueError, TypeError, OSError, UnicodeError):
        # Do not print raw exception details: these may disclose private paths
        # or input content in a public GitHub Actions job.
        raise SystemExit("private_registry_census_unavailable") from None
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
