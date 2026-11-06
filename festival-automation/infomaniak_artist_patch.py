#!/usr/bin/env python3
"""Add festival artist clickthrough to exact verified Infomaniak JS; never deploy."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import argparse

EXPECTED_SHA = '3cbdda3b43d4c71420122dac0d8219f443ea2bd79ac58faee24b15cb7caf1ff2'
SCRIPT = 'https://sarogal.github.io/Ondes-Catalogues/grossesondes/artist-dates.js'
CSS = 'https://sarogal.github.io/Ondes-Catalogues/grossesondes/artist-dates.css'
LINEUP = "f.lineup.map(esc).join(' · ')"
LINEUP_BUTTONS = "f.lineup.map(name=>`<button type=\"button\" class=\"go-artist-link\" data-go-artist=\"${esc(name)}\">${esc(name)}</button>`).join(' · ')"
HISTORY = 'lineup.map(name=>`<span>${esc(name)}</span>`)'
HISTORY_BUTTONS = 'lineup.map(name=>`<button type="button" class="go-artist-link" data-go-artist="${esc(name)}">${esc(name)}</button>`)'
ANCHOR = "document.addEventListener('DOMContentLoaded',async()=>{"
MODAL_ANCHOR = 'function openFestival(f,push){'
ARCHIVE_ANCHOR = 'function openHistoricalFestival(f,push=true){'
HELPER = """// Artistes : retrouver leurs dates françaises Concerts ET Festivals, sans fausse précision.
function ensureGoArtistDatesStyles(){
  if(document.querySelector('link[data-go-artist-dates]'))return;
  const css=document.createElement('link');css.rel='stylesheet';
  css.href=""" + repr(CSS) + """;css.dataset.goArtistDates='1';document.head.appendChild(css);
}
let goArtistDatesPromise = null;
function ensureGoArtistDates(){
  if(window.GrossesOndesArtists?.open)return Promise.resolve(true);
  if(goArtistDatesPromise)return goArtistDatesPromise;
  ensureGoArtistDatesStyles();
  goArtistDatesPromise=new Promise(resolve=>{
    const script=document.createElement('script');script.src=""" + repr(SCRIPT) + """;
    script.onload=()=>resolve(Boolean(window.GrossesOndesArtists?.open));
    script.onerror=()=>resolve(false);
    document.head.appendChild(script);
  }).then(ok=>{if(!ok)goArtistDatesPromise=null;return ok});
  return goArtistDatesPromise;
}
async function openGoArtistDates(name,trigger){
  if(!name||!trigger?.isConnected)return;
  const ok=await ensureGoArtistDates();
  if(!ok||!trigger.isConnected){if(!ok&&trigger.isConnected)toast('Dates artistes temporairement indisponibles.');return;}
  try{window.GrossesOndesArtists.open(name,[...(state.festivals||[]),...(state.festivalArchive||[])]);}
  catch{toast('Impossible d’ouvrir les dates de cet artiste.');}
}
document.addEventListener('click',e=>{
  const button=e.target?.closest?.('button[data-go-artist]');
  if(!button)return;
  e.preventDefault();
  void openGoArtistDates(button.dataset.goArtist,button);
});
"""


def patch(source: bytes) -> bytes:
    if sha256(source).hexdigest() != EXPECTED_SHA:
        raise ValueError('Empreinte app.js inattendue : production modifiée, correctif refusé')
    text = source.decode('utf-8')
    for old in (LINEUP, HISTORY, ANCHOR, MODAL_ANCHOR, ARCHIVE_ANCHOR):
        if text.count(old) != 1:
            raise ValueError('Ancrage absent ou ambigu : ' + old)
    if 'goArtistDatesPromise' in text or 'data-go-artist=' in text:
        raise ValueError('Intégration artistes déjà présente')
    text = text.replace(LINEUP, LINEUP_BUTTONS, 1)
    text = text.replace(HISTORY, HISTORY_BUTTONS, 1)
    text = text.replace(MODAL_ANCHOR, MODAL_ANCHOR + 'ensureGoArtistDatesStyles();', 1)
    text = text.replace(ARCHIVE_ANCHOR, ARCHIVE_ANCHOR + 'ensureGoArtistDatesStyles();', 1)
    text = text.replace(ANCHOR, HELPER + '\n' + ANCHOR, 1)
    if text.count('data-go-artist=') != 2:
        raise ValueError('Deux points d’entrée artistes attendus (festival et archives)')
    if text.count('ensureFestivalTicketWidget().then(ok=>') != 1:
        raise ValueError('Intégration billetterie d’origine non préservée')
    return text.encode('utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=patch(args.source.read_bytes())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(data)
    print('SHA256 original:',EXPECTED_SHA)
    print('SHA256 proposé:',sha256(data).hexdigest())
    print('Octets:',len(data))
    print('Aucune publication Infomaniak effectuée.')


if __name__ == '__main__':
    main()
