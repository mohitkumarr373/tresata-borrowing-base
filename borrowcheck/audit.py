"""Local append-only audit log. Tamper-evident, not cryptographically authenticated."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .evidence import canonical_hash


class AuditLog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, previous TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def append(self, kind: str, data: dict) -> str:
        payload = {"kind": kind, "at": datetime.now(timezone.utc).isoformat(), "data": data}
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT digest FROM events ORDER BY id DESC LIMIT 1").fetchone()
            previous = row[0] if row else "0" * 64
            hashed = canonical_hash({"previous": previous, "payload": payload})
            connection.execute("INSERT INTO events(previous,payload,digest) VALUES(?,?,?)",
                               (previous, json.dumps(payload, sort_keys=True), hashed))
        return hashed

    def events(self) -> list[dict]:
        previous, results = "0" * 64, []
        with self.connect() as connection:
            rows = connection.execute("SELECT previous,payload,digest FROM events ORDER BY id").fetchall()
        for prev, raw, hashed in rows:
            payload = json.loads(raw)
            if prev != previous or hashed != canonical_hash({"previous": prev, "payload": payload}):
                raise ValueError("Audit chain integrity failed")
            results.append({"digest": hashed, **payload})
            previous = hashed
        return results

    def signoff(self, result: dict, reviewer: str, note: str) -> str:
        if result.get("status") != "READY_FOR_REVIEW":
            raise ValueError("A blocked result cannot be signed off")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 120:
            raise ValueError("Reviewer name is required")
        if not isinstance(note, str) or not note.strip() or len(note) > 2000:
            raise ValueError("Review rationale is required")
        self.events()
        return self.append("LOCAL_DEMO_SIGNOFF", {"run_id": result["run_id"],
                          "result_sha256": canonical_hash(result), "reviewer": reviewer.strip(),
                          "note": note.strip(), "legal_authorization": False})
