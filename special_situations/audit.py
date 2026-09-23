"""Read-only summary of deployed encrypted state; never sends mail or pushes state."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from .config import Config, ROOT
from .pipeline import coverage, profile
from .state_sync import StateSync
from .store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    parser.add_argument("--errors", action="store_true", help="Include unresolved filing identities/errors")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    with tempfile.TemporaryDirectory(prefix="bse-audit-") as temp:
        folder = Path(temp)
        sync = StateSync(folder, f"https://github.com/{args.repo}.git", os.environ["STATE_ENCRYPTION_KEY"])
        store = Store(":memory:")
        sync.restore(store)
        print(json.dumps({"state_commit": sync.git("rev-parse", "HEAD").strip(),
                          "encrypted_snapshot_bytes": sum(p.stat().st_size for p in folder.glob("*.enc"))}))
        for day in store.days():
            items = store.items(day)
            cost = sum(part.get("usage", {}).get("cost_usd", 0) for item in items
                       for part in item["state"].get("chunks", {}).values())
            messages = store.db.execute("SELECT sent_at FROM messages WHERE day=?", (day,)).fetchall()
            print(json.dumps({"day": day, **coverage(items), "companies": len({i['filing']['code'] for i in items}),
                              "current_profile_screened": sum(i["state"]["status"] == "done"
                                  and i["state"].get("profile") == profile(Config.from_env()) for i in items),
                              "successful_cached_calls_cost_usd": round(cost, 6),
                              "emails_sent": sum(bool(row[0]) for row in messages),
                              "emails_pending": sum(not row[0] for row in messages)}))
            if args.errors:
                for item in items:
                    if item["state"]["status"] == "error":
                        print(json.dumps({"id": item["filing"]["id"], "company": item["filing"]["company"],
                                          "error": item["state"]["error"], "attempts": item["state"]["attempts"]}))
        store.close()


if __name__ == "__main__":
    main()
