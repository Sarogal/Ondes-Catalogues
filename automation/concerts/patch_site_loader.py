#!/usr/bin/env python3
"""Prépare un patch STRICTEMENT CIBLÉ du JS Concerts réellement en production.

Ne lit ni n'écrase de fichier à distance. N'altère aucun style, aucune carte et
aucune fiche. Prend les originaux fournis par l'utilisateur et crée les nouveaux.
"""
from __future__ import annotations
import argparse
import hashlib
import pathlib
import re

CLOUD = "https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json"
ORIGINAL = (
    "async function init(){try{const response=await fetch('catalogue.json',{cache:'no-store'});"
    "if(!response.ok)throw Error('Catalogue inaccessible');const data=await response.json();"
    "validate(data);state.data=data;"
)
NEW = "async function init(){try{const data=await loadConcertsCatalogue();state.data=data;"

LOADER = """// Catalogue Concerts : GitHub Pages prioritaire, Infomaniak en secours.
const GO_CONCERTS_CLOUD_SOURCE = 'https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json';
async function loadConcertsCatalogue(){
  const urls=[GO_CONCERTS_CLOUD_SOURCE,'catalogue.json'];
  let problem='';
  for(const url of urls){
    try{
      const response=await fetch(url,{cache:'no-store'});
      if(!response.ok)throw Error('HTTP '+response.status);
      const data=await response.json();
      validate(data);
      if(data.schemaVersion!==1||data.mode!=='preview-public-unlisted'||
         data.events.length<127||data.venues.length<53||data.artists.length<193){
        throw Error('Catalogue inattendu ou incomplet');
      }
      return data;
    }catch(err){ problem=url+': '+err.message; }
  }
  throw Error('Sources de concerts indisponibles; '+problem);
}
"""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def patch_js(original):
    if isinstance(original, bytes):
        text = original.decode("utf-8-sig")
    else:
        text = original
    if text.count(ORIGINAL) != 1:
        raise ValueError("Chargement du catalogue différent du code audité : patch refusé")
    if "GO_CONCERTS_CLOUD_SOURCE" in text:
        raise ValueError("Patch déjà présent : refus de double modification")
    text = text.replace(ORIGINAL, NEW).replace(
        "async function init()", LOADER + "\nasync function init()", 1
    )
    if text.count("loadConcertsCatalogue") != 2:
        raise ValueError("Erreur du patch : nombre inattendu d'appels")
    return text


def patch_index(text):
    text = text.decode("utf-8-sig") if isinstance(text, bytes) else text
    pattern = r'(\bsrc=["\x27]app\.js\?v=)[^"\x27]+'
    new, n = re.subn(pattern, r'\g<1>cloud-2026-11-01', text, count=1)
    if n != 1:
        raise ValueError("Lien app.js?v=... absent ou différent : patch index refusé")
    return new


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    parser.add_argument("--index")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    output = pathlib.Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    current = pathlib.Path(args.app).read_bytes()
    edited = patch_js(current)
    (output / "app.js").write_text(edited, encoding="utf-8")
    print("app.js initial SHA256:", sha256(current))
    print("app.js patch SHA256:", sha256(edited.encode("utf-8")))
    if args.index:
        original = pathlib.Path(args.index).read_bytes()
        revised = patch_index(original)
        (output / "index.html").write_text(revised, encoding="utf-8")
        print("index.html initial SHA256:", sha256(original))
    print("Fichiers prêts ; PAS de publication vers Infomaniak.")


if __name__ == "__main__":
    main()
