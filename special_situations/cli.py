from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from .bse import collect_day
from .classifier import Budget, Classifier
from .config import Config, IST, ROOT
from .digest import build_messages, deliver_pending, dispatch
from .pipeline import screen_day
from .state_sync import StateSync
from .store import Store


def planned_dates(existing: list[str], target: date):
    if not existing:
        return [target]
    earliest = min(date.fromisoformat(d) for d in existing)
    # Refresh the two latest completed days for late postings; also fill every missed day.
    start = max(earliest, min(max(date.fromisoformat(d) for d in existing), target - timedelta(days=1)))
    return [start + timedelta(days=i) for i in range(max(0, (target - start).days + 1))]


def run(args):
    load_dotenv(ROOT / ".env")
    cfg = Config.from_env()
    cfg.runtime.mkdir(parents=True, exist_ok=True)
    store = Store(cfg.runtime / "state.sqlite3")
    budget = Budget(cfg.max_run_usd)
    classifier = None
    deadline = time.monotonic() + cfg.run_minutes * 60
    with tempfile.TemporaryDirectory(prefix="bse-state-") as temp:
        sync = None
        if args.workflow:
            remote = os.getenv("STATE_REMOTE") or f"https://github.com/{os.environ['GITHUB_REPOSITORY']}.git"
            sync = StateSync(Path(temp), remote, os.environ["STATE_ENCRYPTION_KEY"])
            sync.restore(store)

        def checkpoint():
            if sync:
                sync.save(store)

        try:
            if args.send:
                deliver_pending(store, checkpoint)
            target = date.fromisoformat(args.date) if args.date else datetime.now(IST).date() - timedelta(days=1)
            if target >= datetime.now(IST).date():
                raise ValueError("Only completed IST filing dates may be screened")
            refresh = [target] if args.date else planned_dates(store.days(), target)
            for day in refresh:
                rows, metadata = collect_day(day)
                store.ingest(day.isoformat(), rows, metadata)
                print(json.dumps({"date": day.isoformat(), "feed": metadata}), flush=True)
                checkpoint()
            # Resume unfinished older days as well as newly fetched ones.
            days = [target.isoformat()] if args.date else [d for d in store.days() if d <= target.isoformat()]
            refreshed_days = {d.isoformat() for d in refresh}
            for day in days:
                items = store.items(day)
                from .pipeline import profile
                subset = items[:args.max_filings] if args.max_filings else items
                reclassify = day in refreshed_days
                needs_ai = any((reclassify and i["state"].get("profile") != profile(cfg)) or (
                    i["state"]["status"] != "done" and (i["state"].get("attempts", 0) < 3 or args.retry_errors))
                    for i in subset)
                if needs_ai and time.monotonic() < deadline:
                    classifier = classifier or Classifier(cfg, budget)
                    stats = screen_day(store, day, cfg, classifier, checkpoint, args.max_filings,
                                       args.retry_errors, deadline, reclassify=reclassify)
                    print(json.dumps({"date": day, **stats}), flush=True)
                previews = build_messages(store, day)
                output = ROOT / "output"
                output.mkdir(exist_ok=True)
                for n, message in enumerate(previews, 1):
                    (output / f"{day}-{n}.html").write_text(message["html"])
                if args.send:
                    sent = dispatch(store, day, checkpoint)
                    print(json.dumps({"date": day, "emails_sent": sent}), flush=True)
            print(json.dumps({"api_calls": budget.calls, "run_cost_or_guard_usd": round(budget.spent, 6)}), flush=True)
        finally:
            checkpoint()
            store.close()


def main():
    parser = argparse.ArgumentParser(description="BSE-wide daily special-situation screening")
    parser.add_argument("--date", help="Completed IST filing date YYYY-MM-DD; default yesterday plus catch-up")
    parser.add_argument("--max-filings", type=int, default=0, help="Deterministic smoke-test sample; 0 = all")
    parser.add_argument("--send", action="store_true", help="Send digest emails (default: preview only)")
    parser.add_argument("--workflow", action="store_true", help="Restore/checkpoint encrypted remote Git state")
    parser.add_argument("--retry-errors", action="store_true", help="Retry review errors after three failed attempts")
    args = parser.parse_args()
    if args.max_filings < 0:
        parser.error("--max-filings must be nonnegative")
    if args.max_filings and args.send:
        parser.error("Sample runs cannot send a production digest")
    run(args)


if __name__ == "__main__":
    main()
