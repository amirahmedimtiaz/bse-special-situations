from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Store:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS days(day TEXT PRIMARY KEY, metadata TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS filings(id TEXT PRIMARY KEY, day TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, day TEXT NOT NULL, data TEXT NOT NULL, sent_at TEXT);
        CREATE INDEX IF NOT EXISTS filings_day ON filings(day);
        """)

    def close(self):
        self.db.close()

    def ingest(self, day: str, rows: list[dict], metadata: dict):
        with self.db:
            previous = self.db.execute("SELECT id FROM filings WHERE day=?", (day,)).fetchall()
            if not {r[0] for r in previous} <= {row["id"] for row in rows}:
                raise ValueError("Previously collected filings disappeared; retain state and review the feed")
            for row in rows:
                revision = fingerprint({k: row[k] for k in ("subject", "body", "attachment", "published")})
                old = self.get(row["id"])
                if old and old["state"]["revision"] == revision:
                    continue
                state = {"revision": revision, "status": "pending", "chunks": {}, "attempts": 0,
                         "notified": old["state"].get("notified") if old else None}
                self.db.execute("INSERT OR REPLACE INTO filings VALUES (?, ?, ?, ?)",
                                (row["id"], day, json.dumps(row), json.dumps(state)))
            metadata = {**metadata, "fetched_at": now()}
            self.db.execute("INSERT OR REPLACE INTO days VALUES (?, ?)", (day, json.dumps(metadata)))

    def get(self, nid):
        row = self.db.execute("SELECT payload, state FROM filings WHERE id=?", (nid,)).fetchone()
        return {"filing": json.loads(row[0]), "state": json.loads(row[1])} if row else None

    def save(self, item):
        with self.db:
            self.db.execute("UPDATE filings SET state=? WHERE id=?",
                            (json.dumps(item["state"]), item["filing"]["id"]))

    def items(self, day: str):
        return [{"filing": json.loads(row[0]), "state": json.loads(row[1])}
                for row in self.db.execute("SELECT payload, state FROM filings WHERE day=? ORDER BY id", (day,))]

    def days(self):
        return [row[0] for row in self.db.execute("SELECT day FROM days ORDER BY day")]

    def metadata(self, day):
        row = self.db.execute("SELECT metadata FROM days WHERE day=?", (day,)).fetchone()
        return json.loads(row[0]) if row else None

    def queue(self, message):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO messages VALUES (?, ?, ?, NULL)",
                            (message["id"], message["day"], json.dumps(message)))

    def pending_messages(self):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT data FROM messages WHERE sent_at IS NULL ORDER BY day,id")]

    def message_sent(self, message):
        with self.db:
            self.db.execute("UPDATE messages SET sent_at=? WHERE id=?", (now(), message["id"]))
            for nid, version in message["versions"].items():
                item = self.get(nid)
                if item:
                    item["state"]["notified"] = version
                    self.db.execute("UPDATE filings SET state=? WHERE id=?", (json.dumps(item["state"]), nid))

    def already_reported(self, day: str, complete: bool):
        messages = self.db.execute("SELECT data FROM messages WHERE day=? AND sent_at IS NOT NULL", (day,))
        return any(json.loads(row[0])["complete"] == complete for row in messages)

    def partitions(self):
        for day in self.days():
            yield day, {"version": 1, "day": day, "metadata": self.metadata(day), "items": self.items(day),
                        "messages": [dict(r) for r in self.db.execute("SELECT * FROM messages WHERE day=?", (day,))]}

    def restore(self, data):
        if data.get("version") != 1:
            raise ValueError("Unsupported snapshot version")
        day = data["day"]
        with self.db:
            if "metadata" in data:
                self.db.execute("INSERT OR REPLACE INTO days VALUES (?,?)", (day, json.dumps(data["metadata"])))
            for item in data["items"]:
                filing = item["filing"]
                if filing["day"] != day:
                    raise ValueError("Snapshot contains mismatched filing date")
                self.db.execute("INSERT OR REPLACE INTO filings VALUES (?,?,?,?)",
                                (filing["id"], day, json.dumps(filing), json.dumps(item["state"])))
            for row in data.get("messages", []):
                self.db.execute("INSERT OR REPLACE INTO messages VALUES (?,?,?,?)",
                                tuple(row[k] for k in ("id", "day", "data", "sent_at")))
