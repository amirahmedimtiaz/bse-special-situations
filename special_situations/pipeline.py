from __future__ import annotations

import copy
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .classifier import BudgetExceeded, PROMPT_VERSION, combine, has_catalyst
from .documents import chunks, read_filing
from .store import fingerprint, now


def profile(cfg):
    return fingerprint([PROMPT_VERSION, cfg.model, cfg.reasoning])


def process(item, cfg, classifier, deadline):
    item = copy.deepcopy(item)
    state, filing = item["state"], item["filing"]
    if state.get("profile") != profile(cfg):
        state.update(profile=profile(cfg), attempts=0, status="pending", chunks={})
        state.pop("skip_reason", None)
    try:
        if time.monotonic() >= deadline:
            raise BudgetExceeded("Runtime guard reached")
        document = read_filing(filing, cfg)
        state["document"] = {k: v for k, v in document.items() if k != "text"}
        reason = "no_text" if document["method"] == "no_text" else (
            "no_catalyst_terms" if not has_catalyst(filing, document["text"]) else "")
        if reason:
            state.update(status="done", skip_reason=reason, updated_at=now(),
                         result={"decision": "needs_review" if reason == "no_text" else "irrelevant",
                                 "findings": [], "warnings": [reason], "policy": PROMPT_VERSION})
            state.pop("error", None)
            return item
        state.pop("skip_reason", None)
        results = []
        for part in chunks(document["text"], cfg.chunk_chars):
            key = classifier.cache_key(filing, part)
            if key not in state["chunks"]:
                if time.monotonic() >= deadline:
                    raise BudgetExceeded("Runtime guard reached")
                state["chunks"][key] = classifier.classify(filing, part)
            results.append(state["chunks"][key]["result"])
        state.update(result=combine(results, document), status="done", updated_at=now())
        state.pop("error", None)
    except BudgetExceeded as exc:
        state.update(status="pending", error=str(exc))
    except Exception as exc:
        state.update(status="error", error=f"{type(exc).__name__}: {exc}"[:600],
                     attempts=state.get("attempts", 0) + 1, updated_at=now())
        state["result"] = {"decision": "needs_review", "findings": [],
                           "warnings": ["Automatic screening could not finish: " + state["error"]]}
    return item


def screen_day(store, day, cfg, classifier, checkpoint=lambda: None, max_filings=0, retry_errors=False,
               deadline=None, reclassify=True):
    deadline = deadline or time.monotonic() + cfg.run_minutes * 60
    items = store.items(day)
    # A deterministic sample, not 'next N pending': rerunning a smoke test must be quiet.
    if max_filings:
        items = items[:max_filings]
    invalidated = False
    if reclassify:
        for item in items:
            if item["state"].get("profile") != profile(cfg) and item["state"]["status"] != "pending":
                item["state"]["status"] = "pending"
                store.save(item)
                invalidated = True
    if invalidated:
        checkpoint()  # Outdated classifications are not completed coverage for this profile.
    if retry_errors:
        for item in items:
            if item["state"]["status"] == "error":
                item["state"]["attempts"] = 0
    pending = iter(item for item in items if not (
        (not reclassify or item["state"].get("profile") == profile(cfg)) and
        (item["state"]["status"] == "done" or item["state"].get("attempts", 0) >= 3)))
    count = 0
    stopped = False
    with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        active = set()

        def submit():
            if stopped or time.monotonic() >= deadline:
                return False
            item = next(pending, None)
            if item is None:
                return False
            active.add(pool.submit(process, item, cfg, classifier, deadline))
            return True

        for _ in range(cfg.workers):
            submit()
        while active:
            done, active = wait(active, timeout=30, return_when=FIRST_COMPLETED)
            for future in done:
                item = future.result()
                store.save(item)
                count += 1
                if item["state"]["status"] == "pending":
                    stopped = True
                if count % 40 == 0:
                    checkpoint()
                    print(f"Checkpoint {day}: {count} processed this run; "
                          f"API cost/guard estimate ${classifier.budget.spent:.4f}", flush=True)
                submit()
    checkpoint()
    return {"processed": count, "coverage": coverage(store.items(day)),
            "api_calls": classifier.budget.calls, "run_cost_usd": round(classifier.budget.spent, 6)}


def coverage(items):
    result = {"total": len(items), "screened": 0, "relevant": 0, "needs_review": 0,
              "errors": 0, "pending": 0, "historical_ocr": 0, "skipped_no_text": 0, "local_filtered": 0,
              "current_policy_processed": 0, "legacy_policy_processed": 0}
    for item in items:
        state = item["state"]
        if state["status"] == "done":
            result["screened"] += 1
            key = "current_policy_processed" if state["result"].get("policy") == PROMPT_VERSION else "legacy_policy_processed"
            result[key] += 1
            decision = state["result"]["decision"]
            if decision in ("relevant", "needs_review"):
                result[decision] += 1
        elif state["status"] == "error":
            result["errors"] += 1
        else:
            result["pending"] += 1
        if state.get("document", {}).get("method") == "ocr":
            result["historical_ocr"] += 1
        if state.get("skip_reason") == "no_text":
            result["skipped_no_text"] += 1
        if state.get("skip_reason") == "no_catalyst_terms":
            result["local_filtered"] += 1
    return result
