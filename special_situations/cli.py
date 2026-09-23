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
from .digest import build_messages, dispatch
from .pipeline import coverage, screen_day
from .state_sync import StateSync
from .store import Store


def planned_dates(existing: list[str], target: date, lookback_days=7):
    if not 1 <= lookback_days <= 31:
        raise ValueError("Lookback must be between 1 and 31 days")
    known = {date.fromisoformat(d) for d in existing if d <= target.isoformat()}
    start = target - timedelta(days=lookback_days - 1)
    if known:
        start = min(start, max(known) + timedelta(days=1))
    selected = {start + timedelta(days=i) for i in range((target - start).days + 1)}
    if known:
        # Internal holes also survive a partially successful previous weekly run.
        earliest = min(known)
        selected |= {earliest + timedelta(days=i) for i in range((target - earliest).days + 1)} - known
    return sorted(selected)


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
            target = date.fromisoformat(args.date) if args.date else datetime.now(IST).date() - timedelta(days=1)
            if target >= datetime.now(IST).date():
                raise ValueError("Only completed IST filing dates may be screened")
            refresh = [target] if args.date else planned_dates(store.days(), target)
            if not args.date:
                refresh = sorted(set(refresh) | {date.fromisoformat(d) for d in store.days()
                    if d <= target.isoformat() and store.metadata(d).get("collection_error")})
            collection_errors = {}
            for day in refresh:
                try:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Runtime guard reached before feed collection")
                    rows, metadata = collect_day(day)
                    store.ingest(day.isoformat(), rows, metadata)
                    print(json.dumps({"date": day.isoformat(), "feed": metadata}), flush=True)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"[:600]
                    collection_errors[day.isoformat()] = error
                    store.collection_failed(day.isoformat(), error)
                    print(json.dumps({"date": day.isoformat(), "collection_error": error}), flush=True)
                checkpoint()
            refreshed_days = {d.isoformat() for d in refresh}
            # Completed historical profiles are left alone; unfinished days remain recoverable.
            days = sorted(refreshed_days | ({d for d in store.days() if d <= target.isoformat()
                and any(i["state"]["status"] != "done" for i in store.items(d))} if not args.date else set()))
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
            previews = build_messages(store, days, collection_errors=collection_errors)
            output = ROOT / "output"
            output.mkdir(exist_ok=True)
            for n, message in enumerate(previews, 1):
                (output / f"weekly-{target}-{n}.html").write_text(message["html"])
            if args.send:
                sent = dispatch(store, days, checkpoint, collection_errors=collection_errors)
                print(json.dumps({"through_date": target.isoformat(), "emails_sent": sent}), flush=True)
            print(json.dumps({"api_calls": budget.calls, "run_cost_or_guard_usd": round(budget.spent, 6)}), flush=True)
            totals = coverage([i for d in days for i in store.items(d)])
            if collection_errors or totals["errors"] or (totals["pending"] and not args.max_filings):
                raise RuntimeError("Incomplete run: feed failures or unfinished filings remain; see logs and encrypted state")
        finally:
            checkpoint()
            store.close()


def main():
    parser = argparse.ArgumentParser(description="BSE-wide weekly small-investor arbitrage screening")
    parser.add_argument("--date", help="One completed IST filing date YYYY-MM-DD; default previous seven days plus catch-up")
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
