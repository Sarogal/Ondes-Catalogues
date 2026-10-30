#!/usr/bin/env python3
"""Découverte uniquement : la base ministérielle ne confirme aucune édition future."""
import argparse
import csv
from difflib import SequenceMatcher
import io
import json
from pathlib import Path
import re
import unicodedata
from urllib.request import Request, urlopen

SOURCE_PAGE = "https://www.data.gouv.fr/datasets/liste-des-festivals-en-france"
SOURCE_URL = "https://www.data.gouv.fr/api/1/datasets/r/47ac11c2-8a00-46a7-9fa8-9b802643f975"
MAX_BYTES = 15_000_000
RELEVANCE = re.compile(r"\b(m[ée]tal|metal|hard[ -]?rock|hardcore|punk|thrash|death|doom|stoner|grind|black[ -]?metal|heavy[ -]?metal)\b", re.I)
NAME_RELEVANCE = re.compile(r"(m[ée]tal|hardcore|hard[ -]?rock|thrash|death|doom|stoner|hell|grind|rock in bourlon)", re.I)
COMMON = re.compile(r"\b(festival|fest|edition|open air|20\d\d)\b", re.I)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower().replace("’", "'"))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = COMMON.sub(" ", value)
    return " ".join(re.findall(r"[a-z0-9]+", value))


def read_ministry_csv(data: bytes) -> list[dict]:
    if len(data) > MAX_BYTES:
        raise ValueError("Ministry CSV too large")
    text = data.decode("utf-8-sig").lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    required = {
        "Nom du festival", "Commune principale de déroulement",
        "Département principal de déroulement", "Sous-catégorie musique",
    }
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Unexpected ministry CSV columns")
    return list(reader)


def known_records(history: dict, calendar: dict) -> list[dict]:
    if history.get("schema") != 2 or calendar.get("schema") != 1:
        raise ValueError("Unknown Grosses Ondes schema")
    if not isinstance(history.get("knownFestivals"), list) or not isinstance(calendar.get("festivals"), list):
        raise ValueError("Invalid Grosses Ondes collections")
    known = []
    for r in history["knownFestivals"] + calendar["festivals"]:
        for name in [r.get("name", "")] + (r.get("aliases") or []):
            if normalize(name):
                known.append({
                    "name": name,
                    "normalized": normalize(name),
                    "department": str(r.get("department", "")).strip(),
                })
    return known


def department_code(row: dict) -> str:
    insee = (row.get("Code Insee commune") or "").strip().upper()
    postal = (row.get("Code postal (de la commune principale de déroulement)") or "").strip()
    if re.match(r"^97[1-9]", insee):
        return insee[:3]
    if re.match(r"^2[AB]", insee):
        return insee[:2]
    if re.match(r"^\d{5}$", insee):
        if insee.startswith("20"):
            return "2A" if int(insee[2:]) < 200 else "2B"
        return insee[:2]
    if re.match(r"^\d{5}$", postal):
        return postal[:3] if postal.startswith(("97", "98")) else postal[:2]
    return ""


def match_existing(name: str, department: str, known: list[dict]) -> tuple[str, float, str]:
    key = normalize(name)
    best = ("", 0.0, "")
    for r in known:
        score = SequenceMatcher(None, key, r["normalized"]).ratio()
        same_dept = bool(department and department == r["department"])
        if score == 1.0 or (score >= .89 and same_dept):
            return r["name"], score, "deja_present_a_controler"
        if score > best[1]:
            best = (r["name"], score, "a_verifier")
    return best


def discover(rows: list[dict], known: list[dict]) -> dict:
    candidates = []
    seen = set()
    for row in rows:
        name = (row.get("Nom du festival") or "").strip()
        genres = (row.get("Sous-catégorie musique") or "").strip()
        if not (NAME_RELEVANCE.search(name) or RELEVANCE.search(genres)):
            continue
        city = (row.get("Commune principale de déroulement") or "").strip()
        department = department_code(row)
        key = (normalize(name), normalize(city), department)
        if not name or key in seen:
            continue
        seen.add(key)
        nearest, similarity, status = match_existing(name, department, known)
        candidates.append({
            "name": name,
            "city": city,
            "department": department,
            "department_name": (row.get("Département principal de déroulement") or "").strip(),
            "genres_ministry": genres,
            "site_ministry": (row.get("Site internet du festival") or "").strip(),
            "ministry_id": (row.get("Identifiant") or "").strip(),
            "nearest_grosses_ondes": nearest if similarity >= .62 else None,
            "similarity": round(similarity, 3),
            "status": status if status == "deja_present_a_controler" else "recherche_officielle_requise",
            "future_edition_confirmed": False,
        })
    return {
        "provenance": {"name": "Ministère de la Culture", "url": SOURCE_PAGE,
                       "licence": "Licence Ouverte 2.0", "historic_reference_year": 2019},
        "safety": "Recherche seule. Aucune date, édition ou localisation future inférée ou publiée.",
        "rows_scanned": len(rows),
        "candidates_found": len(candidates),
        "already_present_or_similar": sum(x["status"] == "deja_present_a_controler" for x in candidates),
        "pending_manual_review": sum(x["status"] == "recherche_officielle_requise" for x in candidates),
        "candidates": candidates,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, help="CSV fourni en local (test hors ligne)")
    p.add_argument("--history", type=Path, default=Path("docs/grossesondes/festival-history.json"))
    p.add_argument("--calendar", type=Path, default=Path("docs/grossesondes/festivals.json"))
    p.add_argument("--output", type=Path, default=Path("/tmp/grossesondes_ministere/rapport.json"))
    args = p.parse_args()
    if args.csv:
        data = args.csv.read_bytes()
    else:
        req = Request(SOURCE_URL, headers={"User-Agent": "GrossesOndes-Research/1.0"})
        with urlopen(req, timeout=50) as response:
            data = response.read(MAX_BYTES + 1)
    rows = read_ministry_csv(data)
    if len(rows) < 1000:
        raise ValueError("Unexpectedly small ministry dataset")
    history = json.loads(args.history.read_text(encoding="utf-8-sig"))
    calendar = json.loads(args.calendar.read_text(encoding="utf-8-sig"))
    report = discover(rows, known_records(history, calendar))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Ministère : {report['rows_scanned']} lignes, {report['candidates_found']} pistes ; aucune publication.")


if __name__ == "__main__":
    main()
