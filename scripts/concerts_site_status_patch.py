#!/usr/bin/env python3
"""Conservative, OFFLINE patch for the live Infomaniak Concerts app.js and styles.css.

Input must be the actual hosting originals. Each audited anchor must appear once.
No remote access, no publication, no catalogue writes, no speculative aliases.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise ValueError("Patch Concerts refusé : ancre absente ou ambiguë (" + label + ")")
    return text.replace(old, new, 1)


def patch_app(original: str) -> str:
    text = original
    text = replace_once(
        text,
        "const getArtist = (id) => state.data.artists.find(a=>a.id===id);",
        """// Équivalences seulement après vérification nominative officielle.
const GO_VERIFIED_ARTIST_IDS = Object.freeze({
  'les-ramoneurs-de-menhirs': 'les-ramoneurs-de-menhir'
});
const canonicalArtistId = id => GO_VERIFIED_ARTIST_IDS[id] || id;
const sameArtist = (left,right) => canonicalArtistId(left) === canonicalArtistId(right);
const getArtist = (id) => state.data.artists.find(a=>a.id===id);""",
        "alias artist IDs",
    )
    text = replace_once(
        text,
        "const formatDay = (d) => new Intl.DateTimeFormat('fr-FR',{weekday:'long',day:'numeric',month:'long',timeZone:'UTC'}).format(day(d));",
        "const formatDay = (d) => new Intl.DateTimeFormat('fr-FR',{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(day(d));",
        "concert date year",
    )
    text = replace_once(
        text,
        "function eventStatus(e){return e.status==='confirmed'?'Confirmé':e.status==='announced'?'Annoncé':e.status==='postponed'?'Reporté':'Annulé';}",
        "function eventStatus(e){return e.status==='confirmed'?'Confirmé':e.status==='announced'?'Annoncé':e.status==='postponed'?'Reporté':'ANNULÉ';}",
        "cancelled text",
    )
    text = replace_once(
        text,
        "if(e.ticketUrl)body.append(element('p'),externalLink('Billetterie directe',e.ticketUrl));",
        """if(e.status==='cancelled'&&safe(e.cancellationSourceUrl))
  body.append(element('p','', 'Événement ANNULÉ — confirmation officielle : '),
              externalLink('Voir la source de l’annulation',e.cancellationSourceUrl));
if(e.status!=='cancelled'&&e.ticketUrl)
  body.append(element('p'),externalLink('Billetterie directe',e.ticketUrl));""",
        "cancellation source and tickets",
    )
    text = replace_once(
        text,
        "const aliases=[a.name,...(a.aliases||[])].map(norm);",
        "const aliases=state.data.artists.filter(x=>sameArtist(x.id,a.id)).flatMap(x=>[x.name,...(x.aliases||[])]).map(norm);",
        "festival aliases",
    )
    text = replace_once(
        text,
        "state.data.events.filter(e=>e.artistIds.includes(a.id)).sort(",
        "state.data.events.filter(e=>e.artistIds.some(id=>sameArtist(id,a.id))).sort(",
        "all artist concerts",
    )
    text = replace_once(
        text,
        "return state.data.events.filter(e=>{const v=getVenue(e.venueId);if(!v)return false;",
        "return state.data.events.filter(e=>{const v=getVenue(e.venueId);if(!v)return false;if(e.status==='cancelled'&&!query)return false;",
        "exclude cancelled from default upcoming (retain searchable)",
    )
    text = replace_once(
        text,
        "status=element('span','confirmed','● '+eventStatus(e))",
        "status=element('span',['confirmed','announced','postponed','cancelled'].includes(e.status)?e.status:'announced','● '+eventStatus(e))",
        "badge by actual status",
    )
    text = replace_once(
        text,
        "$('#artists-count').textContent=new Set(data.events.flatMap(e=>e.artistIds)).size;",
        "$('#artists-count').textContent=new Set(data.events.flatMap(e=>e.artistIds.map(canonicalArtistId))).size;",
        "unique groups",
    )
    return text


def patch_css(original: str) -> str:
    if ".cancelled{" in original or ".postponed{" in original:
        raise ValueError("Patch Concerts refusé : statuts CSS déjà modifiés")
    return replace_once(
        original,
        ".confirmed{font-size:11px;font-weight:800;color:#76d9a0}",
        """.confirmed{font-size:11px;font-weight:800;color:#76d9a0}
.announced{font-size:11px;font-weight:800;color:#bfc4d2}
.postponed{font-size:11px;font-weight:800;color:#f4c26e}
.cancelled{font-size:11px;font-weight:900;color:#ff8585;text-transform:uppercase}
.event-card:has(.cancelled){border-color:#70363d}""",
        "CSS statuses",
    )


def patch_index(original: str) -> str:
    result = original
    for filename in ("app.js", "styles.css"):
        expression = r'((?:src|href)=["\x27]' + re.escape(filename) + r'\?v=)[^"\x27]+'
        replacement = r'\g<1>status-alias-20261113'
        result, n = re.subn(expression, replacement, result)
        if n != 1:
            raise ValueError("Version d'asset Concerts inattendue : " + filename)
    return result


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True,
                        help="app.js réellement téléchargé depuis Infomaniak")
    parser.add_argument("--css", type=Path, required=True,
                        help="styles.css réellement téléchargé depuis Infomaniak")
    parser.add_argument("--index", type=Path,
                        help="index.html hébergé pour bust du cache (optionnel)")
    parser.add_argument("--out", type=Path, required=True,
                        help="Nouveau dossier vide de sortie ; ne jamais écraser l'original")
    args = parser.parse_args()
    paths = [(args.app, patch_app), (args.css, patch_css)]
    if args.index:
        paths.append((args.index, patch_index))
    patched = []
    for source, transform in paths:
        original = source.read_text(encoding="utf-8-sig")
        modified = transform(original)
        patched.append((source.name, original, modified))
    if args.out.exists() and any(args.out.iterdir()):
        raise ValueError("Dossier de sortie non vide : refus d'écrasement")
    args.out.mkdir(parents=True, exist_ok=True)
    for name, original, modified in patched:
        (args.out / name).write_text(modified, encoding="utf-8")
        print(name, "original:", sha256(original), "patch:", sha256(modified))
    print("Correctif prêt, AUCUN déploiement Infomaniak ou GitHub effectué.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
