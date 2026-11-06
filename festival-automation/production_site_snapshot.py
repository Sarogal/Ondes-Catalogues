"""Read-only snapshot of the ACTUAL public Infomaniak festival site.

Never use website/ as a production source. No credentials, writes or deployment.
The ZIP produced by GitHub Actions is private and intentionally short-lived.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

ORIGIN = "https://grosses-ondes.fr"
REQUIRED = (("/festivals/", "festivals/index.html"),
            ("/app.js", "app.js"))
MAX_BYTES = 500_000


def same_origin_url(url):
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.hostname == "grosses-ondes.fr"
            and parsed.port is None and not parsed.username and not parsed.password
            and not parsed.fragment)


class Stylesheets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        row = dict(attrs)
        rel = row.get("rel", "").lower().split()
        href = row.get("href", "")
        if "stylesheet" not in rel or not href:
            return
        url = urljoin(ORIGIN + "/festivals/", href)
        if same_origin_url(url) and urlparse(url).path.endswith(".css"):
            if url not in self.urls:
                self.urls.append(url)


def get_public_bytes(url):
    if not same_origin_url(url):
        raise ValueError("URL hors origine publique autorisee")
    req = Request(url, headers={
        "User-Agent": "GrossesOndes-Festivals-ProductionSnapshot/1.0",
        "Accept": "text/html,application/javascript,text/css,*/*",
    })
    with urlopen(req, timeout=15) as response:
        if not same_origin_url(response.geturl()):
            raise ValueError("Redirection hors origine autorisee")
        payload = response.read(MAX_BYTES + 1)
        if not (200 <= response.status < 300 and 100 <= len(payload) <= MAX_BYTES):
            raise ValueError("Reponse absente, trop courte ou trop grande")
        return payload, response.geturl(), response.headers.get("Content-Type", "")


def snapshot(destination):
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "grossesondes.production-festival-snapshot.v1",
                "capturedAt": datetime.now(timezone.utc).isoformat(),
                "origin": ORIGIN, "files": [], "errors": []}
    html = None

    def capture(url, relative):
        payload, final_url, media_type = get_public_bytes(url)
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        manifest["files"].append({
            "path": relative, "url": final_url, "bytes": len(payload),
            "sha256": sha256(payload).hexdigest(), "contentType": media_type})
        print(f"OK {relative}: {len(payload)} octets, SHA256 {sha256(payload).hexdigest()}")
        return payload

    for path, relative in REQUIRED:
        try:
            data = capture(ORIGIN + path, relative)
            if relative.endswith("index.html"):
                html = data
        except Exception as exc:
            manifest["errors"].append({"url": ORIGIN + path, "error": str(exc)})
            print(f"ECHEC {relative}: {exc}")
    if html:
        parser = Stylesheets()
        parser.feed(html.decode("utf-8", errors="replace"))
        for number, css_url in enumerate(parser.urls[:4], start=1):
            try:
                capture(css_url, f"css/stylesheet-{number}.css")
            except Exception as exc:
                manifest["errors"].append({"url": css_url, "error": str(exc)})
                print(f"CSS non recuperee: {css_url} ({exc})")
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(manifest["files"]) >= len(REQUIRED) and not any(
        error["url"] in {ORIGIN + path for path, _ in REQUIRED}
        for error in manifest["errors"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if not snapshot(args.out):
        raise SystemExit("Impossible de capturer toutes les ressources obligatoires")


if __name__ == "__main__":
    main()
