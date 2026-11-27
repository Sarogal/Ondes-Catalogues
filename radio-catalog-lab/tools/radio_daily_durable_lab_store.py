"""Local SQLite rehearsal store. No CLI, remote access or production key.

The caller supplies a trusted laboratory public key on every open. Only
laboratory-reanchored pointers are accepted. Private keys are never stored.
"""
import base64
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from radio_daily_baseline_verify import strict_json, verify_baseline
from radio_daily_logo_plan import PREVIEW_BASE, EXTENSIONS
from radio_daily_publication_simulator import check_logo, inventory
from radio_daily_v9_generator import digest

_OBJECT = re.compile(r"(?:releases/([a-f0-9]{64})\.json|objects/sha256/([a-f0-9]{64})\.(?:png|jpg|jpeg|webp))")


class DurableLabStore:
    """SQLite transactions serialize independent writers and survive reopen.

    The database belongs in a private local directory on a local filesystem.
    It is a rehearsal backend, not a GitHub Pages publication adapter.
    """

    def __init__(self, path, *, public_key, key_id):
        raw = base64.b64decode(public_key, validate=True)
        if len(raw) != 32 or key_id != "radio-lab-" + digest(raw)[:24]:
            raise ValueError("laboratory key required")
        self.path = Path(path).resolve()
        self.public_key = public_key
        self.key_id = key_id
        with self._connect() as db:
            pointer = self._current(db)
            p = self._verified(db, pointer)
            row = db.execute("SELECT data FROM history WHERE sequence=?", (p["release_sequence"],)).fetchone()
            latest = db.execute("SELECT MAX(sequence) FROM history").fetchone()[0]
            if row is None or row[0] != pointer or latest != p["release_sequence"]:
                raise ValueError("current pointer history mismatch")

    @contextmanager
    def _connect(self, *, create=False, write=False):
        uri = self.path.as_uri() + ("?mode=rwc" if create else "?mode=rw")
        db = sqlite3.connect(uri, uri=True, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @classmethod
    def initialize(cls, path, pointer, body, *, public_key, key_id, legacy_logos=None,
                   objects=None):
        """Create once with an authenticated baseline and complete artwork."""
        obj = cls.__new__(cls)
        raw = base64.b64decode(public_key, validate=True)
        if len(raw) != 32 or key_id != "radio-lab-" + digest(raw)[:24]:
            raise ValueError("laboratory key required")
        obj.path = Path(path).resolve()
        obj.public_key, obj.key_id = public_key, key_id
        p = strict_json(pointer)
        doc = verify_baseline(pointer, body, expected_sha=p["content_sha256"],
                              expected_sequence=p["release_sequence"],
                              public_key=public_key, key_id=key_id)
        legacy_logos, objects = dict(legacy_logos or {}), dict(objects or {})
        required_legacy = {l["url"] for l, name in inventory(doc) if name is None}
        required_objects = {name for _, name in inventory(doc) if name is not None}
        if set(legacy_logos) != required_legacy or set(objects) != required_objects:
            raise ValueError("incomplete or extra bootstrap artwork")
        with obj._connect(create=True, write=True) as db:
            db.execute("CREATE TABLE objects (path TEXT PRIMARY KEY, data BLOB NOT NULL)")
            db.execute("CREATE TABLE legacy (url TEXT PRIMARY KEY, path TEXT NOT NULL)")
            db.execute("CREATE TABLE pointer (id INTEGER PRIMARY KEY CHECK(id=1), data BLOB NOT NULL)")
            db.execute("CREATE TABLE history (sequence INTEGER PRIMARY KEY, data BLOB NOT NULL)")
            obj._put(db, p["content_path"], body)
            for logo, name in inventory(doc):
                url = logo["url"]
                data = legacy_logos[url] if name is None else objects[name]
                check_logo(logo, data)
                if name is None:
                    name = logo["sha256"] + "." + EXTENSIONS[logo["mime_type"]]
                    db.execute("INSERT OR IGNORE INTO legacy VALUES (?,?)",
                               (url, "objects/sha256/" + name))
                    if db.execute("SELECT path FROM legacy WHERE url=?", (url,)).fetchone()[0] != "objects/sha256/" + name:
                        raise ValueError("conflicting legacy logo mapping")
                obj._put(db, "objects/sha256/" + name, data)
            db.execute("INSERT INTO pointer VALUES (1,?)", (pointer,))
            obj._verified(db, pointer)
            db.execute("INSERT INTO history VALUES (?,?)", (p["release_sequence"], pointer))
        return cls(path, public_key=public_key, key_id=key_id)

    @staticmethod
    def _check_path(path, data=None):
        match = _OBJECT.fullmatch(path) if isinstance(path, str) else None
        if match is None:
            raise ValueError("invalid immutable object path")
        if data is not None:
            limit = 10485760 if match.group(1) else 2097152
            if not isinstance(data, bytes) or not 0 < len(data) <= limit:
                raise ValueError("invalid immutable object size")
            if digest(data) != (match.group(1) or match.group(2)):
                raise ValueError("immutable object digest mismatch")

    @staticmethod
    def _current(db):
        row = db.execute("SELECT data FROM pointer WHERE id=1").fetchone()
        if row is None:
            raise ValueError("missing laboratory pointer")
        return row[0]

    def _get(self, db, path):
        self._check_path(path)
        row = db.execute("SELECT data FROM objects WHERE path=?", (path,)).fetchone()
        if row is None:
            raise KeyError(path)
        self._check_path(path, row[0])
        return row[0]

    def _put(self, db, path, data):
        self._check_path(path, data)
        row = db.execute("SELECT data FROM objects WHERE path=?", (path,)).fetchone()
        if row is not None and row[0] != data:
            raise ValueError("immutable object conflict")
        db.execute("INSERT OR IGNORE INTO objects VALUES (?,?)", (path, data))

    def _logo(self, db, url):
        if url.startswith(PREVIEW_BASE):
            return self._get(db, "objects/sha256/" + url[len(PREVIEW_BASE):])
        row = db.execute("SELECT path FROM legacy WHERE url=?", (url,)).fetchone()
        if row is None:
            raise KeyError(url)
        return self._get(db, row[0])

    def _verified(self, db, pointer):
        p = strict_json(pointer)
        doc = verify_baseline(pointer, self._get(db, p["content_path"]),
                              expected_sha=p["content_sha256"],
                              expected_sequence=p["release_sequence"],
                              public_key=self.public_key, key_id=self.key_id)
        for logo, _ in inventory(doc):
            check_logo(logo, self._logo(db, logo["url"]))
        return p

    def current(self):
        with self._connect() as db:
            return self._current(db)

    def get(self, path):
        with self._connect() as db:
            return self._get(db, path)

    def logo(self, url):
        with self._connect() as db:
            return self._logo(db, url)

    def put_immutable(self, path, data):
        with self._connect(write=True) as db:
            self._put(db, path, data)

    def historical(self, sequence):
        """Return a previously activated and reverified signed release."""
        if type(sequence) is not int or sequence < 8:
            raise ValueError("invalid historical sequence")
        with self._connect() as db:
            row = db.execute("SELECT data FROM history WHERE sequence=?", (sequence,)).fetchone()
            if row is None:
                raise KeyError(sequence)
            pointer = row[0]
            p = self._verified(db, pointer)
            if p["release_sequence"] != sequence:
                raise ValueError("historical sequence mismatch")
            return pointer, self._get(db, p["content_path"])

    def compare_and_swap(self, expected, replacement):
        with self._connect(write=True) as db:
            if self._current(db) != expected:
                raise ValueError("publication concurrency conflict")
            old = self._verified(db, expected)
            new = self._verified(db, replacement)
            if new["release_sequence"] != old["release_sequence"] + 1:
                raise ValueError("non-successor laboratory pointer")
            row = db.execute("SELECT data FROM history WHERE sequence=?", (old["release_sequence"],)).fetchone()
            if row is None or row[0] != expected:
                raise ValueError("current pointer history mismatch")
            db.execute("INSERT INTO history VALUES (?,?)", (new["release_sequence"], replacement))
            db.execute("UPDATE pointer SET data=? WHERE id=1", (replacement,))
