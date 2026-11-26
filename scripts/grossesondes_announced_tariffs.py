"""Explicit advertised festival prices; no inference of ticket availability."""
from datetime import date, timedelta
import re
from grossesondes_official_html_edition import VisibleParagraphs, fold, explicit_ranges, CANCEL

WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
AMOUNT = r"\d{1,4}(?:[,.]\d{2})?"
LABEL = r"(?:[1-7] jours?|" + "|".join(WEEKDAYS) + r")"
PREFIX = "Tarifs annoncés — "


class TariffBlocks(VisibleParagraphs):
    def handle_starttag(self, tag, attrs):
        if tag in ("nav", "footer", "aside", "header"):
            attrs = list(attrs) + [("hidden", None)]
        super().handle_starttag(tag, attrs)


def _valid_label(label, start, end):
    duration = (end - start).days + 1
    if not 1 <= duration <= 7:
        return False
    if label[0].isdigit():
        n = int(label[0])
        return n <= duration and label == str(n) + (" jour" if n == 1 else " jours")
    return label in {WEEKDAYS[(start + timedelta(days=i)).weekday()] for i in range(duration)}


def _money(value):
    return value.replace(".", ",") + " €"


def _render(offers, age):
    if not offers or len(offers) > 8:
        return None
    chunks = []
    for label, (minimum, amount, onsite) in offers.items():
        chunks.append("Pass " + label + " : " + ("dès " if minimum else "") + amount
                      + (", sur place " + onsite if onsite else ""))
    if age is not None:
        chunks.append("Moins de " + str(age) + " ans : gratuit")
    summary = PREFIX + " ; ".join(chunks)
    return summary if len(summary) <= 350 else None


def parse_announced_tariffs(value, row):
    """Only deterministic canonical output; factual proof remains live HTML."""
    if not isinstance(value, str) or not value.startswith(PREFIX) or len(value) > 350:
        return None
    try:
        start, end = date.fromisoformat(row["startDate"]), date.fromisoformat(row["endDate"])
        offers, age = {}, None
        for chunk in value[len(PREFIX):].split(" ; "):
            m = re.fullmatch(r"Pass (" + LABEL + r") : (dès )?(" + AMOUNT +
                             r") €(?:, sur place (" + AMOUNT + r") €)?", chunk)
            if m:
                label = m[1]
                if label in offers or not _valid_label(label, start, end) or (m[2] and m[4]):
                    return None
                offers[label] = (bool(m[2]), _money(m[3]), _money(m[4]) if m[4] else None)
                continue
            m = re.fullmatch(r"Moins de (\d{1,2}) ans : gratuit", chunk)
            if not m or age is not None or not 1 <= int(m[1]) <= 17:
                return None
            age = int(m[1])
        return (offers, age) if _render(offers, age) == value else None
    except (ValueError, KeyError, TypeError):
        return None


def announced_tariffs(html, row, today, edition_city):
    """Read one current-edition tariff list or consecutive pass cards.

    Exact edition/city proof is supplied by the existing independent verifier.
    The preceding visible announcement must carry the same dates; reject any
    intervening old edition or incompatible dates. No sale status is invented.
    """
    try:
        start, end = date.fromisoformat(row["startDate"]), date.fromisoformat(row["endDate"])
        if (start < date.fromisoformat(today) or not 1 <= (end-start).days+1 <= 7
                or not isinstance(html, str) or not 0 < len(html) <= 650_000
                or not edition_city(html, row)):
            return None
        parser = TariffBlocks()
        parser.feed(html)
        parser.close()
        blocks = [" ".join(fold(s).split()) for s in
                  " ".join(parser.parts).split(parser.SEP) if s.strip()]
        headings = [i for i, block in enumerate(blocks) if block in ("tarifs", "billetterie")]
        # Navigation labels can occur, but only one section with a priced pass
        # immediately after its heading may supply a tariff grid.
        candidates = []
        for i in headings:
            if i + 1 >= len(blocks) or not re.match(r"pass " + LABEL + r"\b", blocks[i+1]):
                continue
            prefix = " ".join(blocks[:i])
            intervals = {(a,b) for _,_,a,b in explicit_ranges(prefix, start.year)}
            if ((start,end) not in intervals or any(a < start or b > end for a,b in intervals)
                    or CANCEL.search(prefix)):
                continue
            # The last explicit year before the tariff section must be current.
            years = re.findall(r"(?<!\d)20[2-4]\d(?!\d)", prefix)
            if not years or years[-1] != str(start.year):
                continue
            offers, age, card_ages = {}, None, []
            j = i + 1
            while j < len(blocks):
                block = blocks[j]
                m = re.fullmatch(r"pass (" + LABEL + r")\s*:\s*(a partir de\s+)?(" +
                                 AMOUNT + r")\s*€", block)
                onsite = None
                if m:
                    label, minimum, amount = m[1], bool(m[2]), _money(m[3])
                    j += 1
                else:
                    m = re.fullmatch(r"pass (" + LABEL + r")", block)
                    if not m:
                        break
                    if j + 2 >= len(blocks):
                        return None
                    price = re.fullmatch("(" + AMOUNT + r")\s*€", blocks[j+1])
                    local = re.fullmatch("(" + AMOUNT + r")\s*€\s+sur place", blocks[j+2])
                    if not price or not local:
                        return None
                    label, minimum, amount, onsite = m[1], False, _money(price[1]), _money(local[1])
                    j += 3
                    child = re.fullmatch(r"gratuit\s*-\s*(\d{1,2})\s+ans", blocks[j]) if j < len(blocks) else None
                    card_ages.append(int(child[1]) if child else None)
                    if child:
                        j += 1
                    if j < len(blocks) and blocks[j] in ("je reserve", "reserver", "acheter"):
                        j += 1
                if label in offers or not _valid_label(label, start, end):
                    return None
                offers[label] = (minimum, amount, onsite)
            if j < len(blocks) and re.match(r"pass\b", blocks[j]):
                return None
            if card_ages and all(x is not None and x == card_ages[0] for x in card_ages):
                age = card_ages[0] if 1 <= card_ages[0] <= 17 else None
            # Do not silently combine distinct list and card schemes.
            if card_ages and len(card_ages) != len(offers):
                return None
            summary = _render(offers, age)
            if summary:
                candidates.append(summary)
        return candidates[0] if candidates and len(set(candidates)) == 1 else None
    except (ValueError, KeyError, TypeError, UnicodeError):
        return None
