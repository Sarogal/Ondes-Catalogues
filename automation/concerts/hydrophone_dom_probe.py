#!/usr/bin/env python3
"""Official Hydrophone SPIP DOM diagnostic. Output only small public markup fragments."""
import re,json
from html.parser import HTMLParser
from urllib.request import Request,urlopen

PAGES=["https://hydrophone.fr/-Agenda-.html",
       "https://hydrophone.fr/-Les-Indisciplinees-.html",
       "https://hydrophone.fr/REVNOIR-ICE-SEALED-EYES.html"]
TERMS=["REVNOIR-ICE-SEALED-EYES.html","MERYL-STREEK-CHEST-LIBRARY-CARD.html",
       "KatzPascale-577.html"]
class Tags(HTMLParser):
    def __init__(self):super().__init__();self.tags=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ("time","li","article","a","div","span") and (
            "date" in str(a.get("class","")).lower() or
            "event" in str(a.get("class","")).lower() or
            "programme" in str(a.get("class","")).lower() or
            "datetime" in a or "data-date" in a):
            if len(self.tags)<30:self.tags.append((tag,{k:str(v)[:110] for k,v in a.items()}))

def main():
  for url in PAGES:
    with urlopen(Request(url,headers={"User-Agent":"GrossesOndesConcertWatch/0.1 (read-only)"}),timeout=18) as res:
        page=res.read(900000).decode("utf-8","replace")
    p=Tags();p.feed(page)
    occurrences={}
    for term in TERMS:
      m=re.search(re.escape(term),page,re.I)
      if not m:continue
      around=page[max(0,m.start()-750):m.start()+950]
      around=re.sub(r"data:image/[^'\"\s>]+","[INLINE-IMAGE]",around)
      around=re.sub(r"\s+"," ",around)
      occurrences[term]=around[:1200]
    metas=re.findall(r'<(?:meta|time)\b[^>]{1,300}>',page,re.I)
    year_mentions=[m.group() for m in re.finditer(r'202[67]|(?i:datePublished|dateStart|startDate)',page)][:10]
    print(json.dumps({"url":url,"size":len(page),"dateTags":p.tags[:18],
          "sourceContext":occurrences,"metaTimes":metas[:8],
          "yearMarkers":year_mentions},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
