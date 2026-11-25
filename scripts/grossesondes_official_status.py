"""Conservative explicit status evidence for a signed festival edition.

No status is inferred from a missing date, unavailable site, ticket sales,
an artist's cancellation, or an unqualified old edition. A single signed
official source is sufficient when its visible statement names the edition.
"""
from datetime import date
import re
import unicodedata
from urllib.parse import urlsplit


def fold(value):
    return " ".join(re.findall(r"[a-z0-9]+", "".join(
        c for c in unicodedata.normalize("NFKD", str(value)).casefold()
        if not unicodedata.combining(c))))


CANCELLED = "Annulé"
POSTPONED = "Reporté"
STATUS_MESSAGES = {
    CANCELLED: "Annulation de l’édition confirmée sur le site officiel ; dates et programmation initiales conservées.",
    POSTPONED: "Report de l’édition confirmé sur le site officiel ; dates initiales conservées en attendant la confirmation des nouvelles dates.",
}
STATUS_FIELDS = frozenset({"status", "cancelled", "showOnMap",
                           "verificationStatus", "lastVerified", "auditSources"})


def edition_identity(row):
    try:
        name = row["name"]
        if not isinstance(name, str) or not 3 <= len(name) <= 180:
            return None
        end_name = re.search(r"\s+(20[2-4]\d)$", name)
        start = row.get("startDate")
        if start is not None:
            year = str(date.fromisoformat(start).year)
            end = row.get("endDate")
            if end is not None and date.fromisoformat(end).year != int(year):
                return None
            if end_name and end_name[1] != year:
                return None
        elif end_name and row.get("endDate") is None:
            year = end_name[1]
        else:
            return None
        brand = fold(name[:end_name.start()] if end_name else name)
        if len(brand) < 3:
            return None
        return brand, year
    except (KeyError, ValueError, TypeError):
        return None


def explicit_statuses(blocks, row):
    identity = edition_identity(row)
    if identity is None:
        return set()
    brand, year = map(re.escape, identity)
    # Entire visible statement must refer to the festival itself, never to
    # a support act, an adjacent listing, or a fragment of a longer phrase.
    subject = (r"(?:(?:le|la|l) )?" + brand + " " + year
               + r"|(?:l )?edition " + year + r" (?:du|de la|de l|de) " + brand)
    subject = "(?:" + subject + ")"
    verbs = r"(?:est |sera |a ete |doit etre )?"
    endings = {
        CANCELLED: r"(?:annule|annulee|cancelled|canceled)",
        POSTPONED: r"(?:reporte|reportee|postponed)",
        "maintained": r"(?:maintenu|maintenue|confirmed|confirme|confirmee|n est pas annule|n est pas annulee|n est pas reporte|n est pas reportee)",
    }
    results = set()
    for block in blocks:
        if block.get("tag") not in ("h1", "h2", "h3", "p"):
            continue
        raw = block.get("text")
        if not isinstance(raw, str) or len(raw) > 1200:
            continue
        for sentence in re.split(r"[.!?;\n]+", raw):
            phrase = fold(sentence)
            for status, ending in endings.items():
                if re.fullmatch(subject + " " + verbs + ending, phrase):
                    results.add(status)
            for status, prefix in ((CANCELLED, "annulation"), (POSTPONED, "report")):
                if re.fullmatch(prefix + r" (?:du|de la|de l|de) " + subject, phrase):
                    results.add(status)
                if re.fullmatch(subject + " " + prefix, phrase):
                    results.add(status)
    return results


def apply_status(row, status):
    if status not in STATUS_MESSAGES or row.get("cancelled") is True:
        return None
    if row.get("status") not in ("Annoncé", "Confirmé", "Dates à venir", POSTPONED):
        return None
    if row.get("status") == POSTPONED and status != CANCELLED:
        return None
    updated = dict(row, status=status, showOnMap=False,
                   verificationStatus=STATUS_MESSAGES[status])
    if status == CANCELLED:
        updated["cancelled"] = True
    return updated


def valid_status_delta(old, new):
    expected = apply_status(old, new.get("status"))
    if expected is None:
        return False
    changed = {k for k in set(old) | set(new)
               if (k in old) != (k in new) or old.get(k) != new.get(k)}
    if not changed or not changed <= STATUS_FIELDS or "status" not in changed:
        return False
    if any((k in expected) != (k in new) or expected.get(k) != new.get(k)
           for k in set(expected) | set(new)
           if k not in {"lastVerified", "auditSources"}):
        return False
    try:
        verified = date.fromisoformat(new["lastVerified"])
        if old.get("lastVerified") and verified < date.fromisoformat(old["lastVerified"]):
            return False
        before = old.get("auditSources") or []
        after = new.get("auditSources")
        site = urlsplit(old["officialSite"])
        return (site.scheme == "https" and bool(site.hostname)
                and isinstance(before, list) and isinstance(after, list)
                and bool(after) and len(after) <= 20
                and after[:len(before)] == before
                and any(isinstance(u, str) and urlsplit(u).hostname == site.hostname
                        for u in after)
                and all(isinstance(u, str) and urlsplit(u).scheme == "https"
                        and urlsplit(u).hostname == site.hostname
                        for u in after[len(before):]))
    except (TypeError, ValueError, KeyError):
        return False
