#!/usr/bin/env python3
"""Read-only primary-source Hydrophone venue probe; no publication.
Extract textual evidence from official programming and event-specific pages.
"""
import json,re,os
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import Request,urlopen

HOME="https://hydrophone.fr/"
EVENTS={
 "Revnoir + Ice Sealed Eyes":"https://hydrophone.fr/REVNOIR-ICE-SEALED-EYES.html",
 "Meryl Streek + Chest. + Library Card":"https://hydrophone.fr/MERYL-STREEK-CHEST-LIBRARY-CARD.html",
 "KatzPascale":"https://hydrophone.fr/KatzPascale-577.html"
}
class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.skip=0
    def handle_starttag(self,t,a):
        if t in ("script","style","noscript"):self.skip+=1
    def handle_endtag(self,t):
        if t in ("script","style","noscript"):self.skip=max(0,self.skip-1)
    def handle_data(self,d):
        if not self.skip:self.parts.append(d)

def fetch(url):
    s=urlsplit(url)
    if s.scheme!="https" or s.hostname!="hydrophone.fr" or s.query or s.fragment:
        raise ValueError("Unapproved official URL")
    with urlopen(Request(url,headers={"User-Agent":
         "GrossesOndesConcertWatch/0.1 (research only)"}),timeout=17) as response:
        if response.geturl()!=url:raise ValueError("Redirect to unverified URL")
        page=response.read(950_000).decode("utf-8","replace")
    p=Visible();p.feed(page)
    return " ".join(" ".join(p.parts).split())

def main():
    home=fetch(HOME)
    results=[]
    for name,url in EVENTS.items():
        try:
            text=fetch(url)
            # First-party event page AND main programming must agree on the
            # named bill, with no inferred year from a yearless detail alone.
            in_calendar=bool(re.search(re.escape(name),home,re.I))
            time=re.search(r"\b([01]?\d|2[0-3])h([0-5]\d)?\b",text,re.I)
            room=re.search(r"\bHydrophone\s*-\s*(Grande salle|Club)\b",text,re.I)
            genre=re.search(r"\b(post.punk|punk|metalcore|hardcore|m[eé]tal|grunge)\b",text,re.I)
            day=re.search(r"\b(0?[1-9]|[12]\d|3[01])\s+(?:f[eé]vr|nov)\b",text,re.I)
            # Dates are suggestions until annual page context is verified.
            results.append({"title":name,"officialDetail":url,
                "officialAgendaMatches":in_calendar,
                "dateOnDetailHasNoYear":bool(day),
                "eventRoom":room.group(0) if room else None,
                "genreOnIndividualPage":genre.group(0) if genre else None,
                "localTimeText":time.group(0) if time else None,
                "publicationAllowed":False})
        except Exception as exc:
            results.append({"title":name,"sourceErrorType":type(exc).__name__,
                            "publicationAllowed":False})
    report={"source":"Hydrophone, Lorient","homepageFetched":True,
            "eventsChecked":len(results),"publicationAllowed":False,
            "results":results}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    with open(os.environ.get("GITHUB_STEP_SUMMARY","/dev/null"),
              "a",encoding="utf-8") as f:
        f.write("### Hydrophone — vérification réelle des fiches, aucune publication\n\n")
        for e in results:
            f.write(f"- {e['title']}: agenda={e.get('officialAgendaMatches')}, "
                    f"genre={e.get('genreOnIndividualPage')}, "
                    f"salle={e.get('eventRoom')}, heure={e.get('localTimeText')}, "
                    f"erreur={e.get('sourceErrorType')}\n")
if __name__=="__main__":main()
