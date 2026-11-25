"""First-party tariff grids tied to one explicit edition and opening date.

No inferred availability. Old tables before the current announcement are
ignored; repeated responsive layouts must agree cell by cell.
"""
from datetime import date
import re
from grossesondes_official_html_edition import VisibleText, fold, explicit_ranges, MONTHS, CANCEL

def words(value):
    return " ".join(re.findall(r"[a-z0-9]+", fold(value)))

class TicketTables(VisibleText):
    def __init__(self):
        super().__init__()
        self.context = []
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.block = None
        self.invalid = False

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if self.hidden() or any(t in ("nav", "footer", "header", "aside") for t, _ in self.stack):
            return
        if tag == "table":
            if self.table is not None:
                self.invalid = True
                return
            self.table = []
            self.block = None
        elif self.table is not None:
            if tag == "tr":
                self.row = []
            elif tag in ("td", "th") and self.row is not None:
                if any(k in ("rowspan", "colspan") and v != "1" for k, v in attrs):
                    self.invalid = True
                self.cell = []
        elif tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.block = (tag, [])

    def handle_data(self, data):
        if not self.hidden():
            if self.cell is not None:
                self.cell.append(data)
            elif self.block is not None:
                self.block[1].append(data)

    def handle_endtag(self, tag):
        if not self.hidden():
            if tag in ("td", "th") and self.cell is not None and self.row is not None:
                self.row.append(" ".join(" ".join(self.cell).split()))
                self.cell = None
            elif tag == "tr" and self.row is not None and self.table is not None:
                self.table.append(self.row)
                self.row = None
            elif tag == "table" and self.table is not None:
                if not self.invalid and len(self.tables) < 30:
                    self.tables.append((self.context[-8:], self.table))
                self.table = None
                self.invalid = False
                self.row = self.cell = None
            elif self.block is not None and tag == self.block[0]:
                value = " ".join(" ".join(self.block[1]).split())
                if value:
                    self.context.append(value[:1000])
                    self.context = self.context[-8:]
                self.block = None
        super().handle_endtag(tag)

def _money(value):
    if words(value) == "pas de prevente":
        return "pas de prévente"
    if words(value) == "gratuit":
        return "gratuit"
    m = re.fullmatch(r"(\d{1,4}(?:[,.]\d{2})?)\s*€", value.strip())
    return m[1].replace(".", ",") + " €" if m else None

def _grid(table, brand):
    if not 2 <= len(table) <= 10 or len(table[0]) not in (2, 3):
        return None
    header = table[0]
    if not re.search(r"\b" + re.escape(brand) + r"\b", words(header[0])):
        return None
    stages = [words(x) for x in header[1:]]
    if not all(x in ("prevente", "apres la prevente") for x in stages) or len(set(stages)) != len(stages):
        return None
    out = {}
    for row in table[1:]:
        if len(row) != len(header):
            return None
        label = words(row[0])
        m = re.fullmatch(r"pass ([1-7]) jours?", label)
        age = re.fullmatch(r"moins de (\d{1,2}) ans accompagne(?: entree sans pass)?", label)
        if m:
            k = ("pass", int(m[1]))
        elif age and 1 <= int(age[1]) <= 17:
            k = ("age", int(age[1]))
        else:
            return None
        for stage, raw in zip(stages, row[1:]):
            value = _money(raw)
            if value is None or (stage == "apres la prevente" and value == "pas de prévente"):
                return None
            if k[0] == "age" and value != "gratuit":
                return None
            key = (*k, stage)
            if key in out:
                return None
            out[key] = value
    return out

def _summary(opening, cells):
    categories = {(kind, n) for kind, n, _ in cells}
    if not any(k == "pass" for k, _ in categories):
        return None
    chunks = []
    for kind, n in sorted(categories, key=lambda k: (k[0] != "pass", k[1])):
        before = cells.get((kind, n, "prevente"))
        after = cells.get((kind, n, "apres la prevente"))
        if before is None or after is None:
            return None
        if kind == "age":
            if before != after or before != "gratuit":
                return None
            chunks.append(f"Moins de {n} ans accompagnés : gratuit")
        else:
            prefix = before if before == "pas de prévente" else "prévente " + before
            chunks.append(f"Pass {n} jour{'s' if n > 1 else ''} : {prefix}, après prévente {after}")
    result = f"Préventes annoncées à partir du {opening.strftime('%d/%m/%Y')} — " + " ; ".join(chunks)
    return result if len(result) <= 350 else None

def dated_ticket_table_summary(html, row, today):
    try:
        start, end = date.fromisoformat(row["startDate"]), date.fromisoformat(row["endDate"])
        brand = words(re.sub(r"\b20[2-4]\d\b", "", row["name"]))
        if len(brand.replace(" ", "")) < 8 or end < start or end < date.fromisoformat(today):
            return None
        if not isinstance(html, str) or not 0 < len(html) <= 650_000:
            return None
        parser = TicketTables()
        parser.feed(html)
        parser.close()
        combined, openings = {}, set()
        for context, table in parser.tables:
            grid = _grid(table, brand)
            if not grid:
                continue
            # The named CURRENT edition must precede the table; a presale
            # announcement must follow it. No older unlabelled grid qualifies.
            anchor = None
            for i, raw in enumerate(context):
                w = words(raw)
                ranges = {(a, b) for _, _, a, b in explicit_ranges(fold(raw), start.year)}
                if re.search(r"\b" + re.escape(brand) + r"\b", w) and ranges:
                    anchor = i if ranges == {(start, end)} and not CANCEL.search(fold(raw)) else None
                elif re.search(r"\b(?:edition|festival)\b", w) and re.search(r"\b20[2-4]\d\b", w) and not ranges:
                    anchor = None
            if anchor is None:
                continue
            local = context[anchor+1:]
            opening = set()
            for raw in local:
                match = re.search(r"\b(?:les )?preventes? (?:seront disponibles|ouvriront|debuteront) (?:a partir du|le) (\d{1,2}) ([a-z]+) (20[2-4]\d)\b", words(raw))
                if match and match[2] in MONTHS:
                    opening.add(date(int(match[3]), MONTHS[match[2]], int(match[1])))
            if len(opening) != 1 or next(iter(opening)) > start:
                continue
            openings.update(opening)
            if any(k in combined and combined[k] != v for k, v in grid.items()):
                return None
            combined.update(grid)
        if len(openings) != 1:
            return None
        return _summary(next(iter(openings)), combined)
    except (TypeError, ValueError, KeyError, UnicodeError):
        return None

def parse_dated_ticket_summary(value):
    """Canonical text proof shape; factual authority remains the Publisher."""
    if not isinstance(value, str) or len(value) > 350:
        return None
    m = re.fullmatch(r"Préventes annoncées à partir du (\d{2})/(\d{2})/(\d{4}) — (.+)", value)
    if not m:
        return None
    try:
        opening = date(int(m[3]), int(m[2]), int(m[1]))
        cells = {}
        for chunk in m[4].split(" ; "):
            p = re.fullmatch(r"Pass ([1-7]) jours? : (pas de prévente|prévente \d{1,4}(?:,\d{2})? €), après prévente (\d{1,4}(?:,\d{2})? €)", chunk)
            a = re.fullmatch(r"Moins de (\d{1,2}) ans accompagnés : gratuit", chunk)
            if p:
                k = ("pass", int(p[1]))
                before = p[2].removeprefix("prévente ")
                after = p[3]
            elif a and 1 <= int(a[1]) <= 17:
                k = ("age", int(a[1]))
                before = after = "gratuit"
            else:
                return None
            if (*k, "prevente") in cells:
                return None
            cells[(*k, "prevente")] = before
            cells[(*k, "apres la prevente")] = after
        return (opening, cells) if _summary(opening, cells) == value else None
    except (ValueError, TypeError):
        return None
