#!/usr/bin/env python3
"""Read-only diagnostic of La Carène's actual HTML; no personal data, no publication."""
import re
from html.parser import HTMLParser
from urllib.request import Request,urlopen

URLS=["https://www.lacarene.fr/-agenda-.html",
      "https://www.lacarene.fr/-agenda-.html?debut_agenda=25",
      "https://www.lacarene.fr/mary-bell-prisonnier-du-temps.html"]
KEY=re.compile(r"mary.bell|prisonnier.du.temps|metalearth|recidiv|agenda|concert|date|event",re.I)

class Probe(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors=[]
        self.stack=[]
        self.attributes=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="a" and a.get("href"):
            self.stack.append([a["href"],[]])
        else:self.stack.append(None)
        if any(KEY.search(str(a.get(k,""))) for k in ("class","id","itemprop")):
            if len(self.attributes)<60:
                self.attributes.append({"tag":tag,"class":a.get("class"),
                                        "id":a.get("id"),"itemprop":a.get("itemprop")})
    def handle_data(self,data):
        if self.stack:
            for x in reversed(self.stack):
                if x is not None:
                    x[1].append(data)
                    break
    def handle_endtag(self,tag):
        if not self.stack:return
        a=self.stack.pop()
        if a:
            label=" ".join(" ".join(a[1]).split())
            self.anchors.append((a[0],label[:180]))

def main():
    for url in URLS:
        req=Request(url,headers={"User-Agent":"GrossesOndesConcertWatch/0.1 (discovery only)"})
        try:
            with urlopen(req,timeout=15) as response:
                html=response.read(1300000).decode("utf-8","replace")
                final=response.geturl()
            p=Probe()
            p.feed(html)
            print("SOURCE",url,"FINAL",final,"BYTES",len(html),
                  "LINKS",len(p.anchors))
            for link,title in p.anchors:
                if (KEY.search(link) or KEY.search(title)) and "facebook" not in link:
                    print("EVENT_LINK",repr(link[:180]),repr(title))
            print("ELEMENT_CLASSES",repr(p.attributes[:30]))
            for phrase in ("mary-bell","prisonnier-du-temps",
                           "Metalearth","RECIDIV","Début :","28 novembre"):
                match=re.search(re.escape(phrase),html,re.I)
                if match:
                    sample=re.sub(r"\s+"," ",html[max(0,match.start()-350):
                                                 match.end()+650])
                    print("HTML_NEAR",phrase,repr(sample[:1200]))
        except Exception as exc:
            print("SOURCE_ERROR",url,type(exc).__name__,str(exc)[:120])
if __name__=="__main__":main()
