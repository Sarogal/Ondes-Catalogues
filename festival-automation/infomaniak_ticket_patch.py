#!/usr/bin/env python3
"""Patch only the byte-identified TRUE Infomaniak production app.js.

No site writes: generates a candidate file for review/deployment.
The widget is lazy-loaded from GitHub Pages so SPA entry from home also works.
"""
from hashlib import sha256
from pathlib import Path
import argparse

EXPECTED_APP_SHA = '8f01aad82be475b5df5a2a94dcf37f60c408775e7d339cd7471eb234585ae4ea'
WIDGET_BASE = 'https://sarogal.github.io/Ondes-Catalogues/grossesondes/'
HELPER = '''// Optional, per-category ticket widget. Lazy-load from every SPA entry route.
let festivalTicketWidgetPromise = null;
function ensureFestivalTicketWidget(){
  if(window.GrossesOndesTickets?.render)return Promise.resolve(true);
  if(festivalTicketWidgetPromise)return festivalTicketWidgetPromise;
  festivalTicketWidgetPromise = new Promise(resolve=>{
    if(!document.querySelector('link[data-go-festival-tickets]')){
      const css=document.createElement('link');css.rel='stylesheet';
      css.href=''' + repr(WIDGET_BASE + 'ticket-availability.css') + ''';
      css.dataset.goFestivalTickets='1';document.head.appendChild(css);
    }
    const script=document.createElement('script');
    script.src=''' + repr(WIDGET_BASE + 'ticket-availability.js') + ''';
    script.onload=()=>resolve(Boolean(window.GrossesOndesTickets?.render));
    script.onerror=()=>resolve(false);
    document.head.appendChild(script);
  }).then(ok=>{if(!ok)festivalTicketWidgetPromise=null;return ok});
  return festivalTicketWidgetPromise;
}
'''
MOUNT = '''const ticketSlot=f?.ticketAvailability?document.createElement('div'):null;
if(ticketSlot){
  const modal=$('.festival-modal',bg),links=$('.modal-links',bg);
  if(modal){
    if(links)modal.insertBefore(ticketSlot,links);else modal.appendChild(ticketSlot);
    ensureFestivalTicketWidget().then(ok=>{
      if(!ok||!ticketSlot.isConnected)return;
      try{window.GrossesOndesTickets.render(ticketSlot,f)}catch{ticketSlot.remove()}
    });
  }
}
'''
TARGET = 'function openFestival(f,push){'
SLOT = "</div></article>`;bg.addEventListener('click',e=>{if(e.target===bg||e.target.closest('.modal-close'))closeFestival(true)});document.body.appendChild(bg);"


def patch(source):
    if sha256(source).hexdigest() != EXPECTED_APP_SHA:
        raise ValueError('La production a change : empreinte de app.js inattendue, patch refuse')
    code=source.decode('utf-8')
    if code.count(TARGET)!=1 or code.count(SLOT)!=1:
        raise ValueError('Structure de openFestival inconnue : patch refuse')
    code=code.replace(TARGET,HELPER+'\n'+TARGET,1)
    code=code.replace(SLOT,"</div></article>`;\n"+MOUNT+"bg.addEventListener('click',e=>{if(e.target===bg||e.target.closest('.modal-close'))closeFestival(true)});document.body.appendChild(bg);",1)
    if code.count('ensureFestivalTicketWidget().then(ok=>')!=1:
        raise ValueError('Patch absent ou applique plusieurs fois')
    return code.encode('utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=patch(args.source.read_bytes())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(result)
    print('Source SHA256:',EXPECTED_APP_SHA)
    print('Patch SHA256: ',sha256(result).hexdigest())
    print('Patch length: ',len(result))


if __name__ == '__main__':
    main()
