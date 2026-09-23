import json
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from special_situations import classifier, cli, digest, pipeline
from special_situations.classifier import Budget, Classifier, PROMPT_VERSION
from special_situations.config import Config
from special_situations.store import Store


def finish(store, filing, result):
    item = store.get(filing["id"])
    item["state"].update(status="done", profile=pipeline.profile(Config()),
        result={"decision": result["decision"], "findings": [result], "warnings": [], "policy": PROMPT_VERSION})
    store.save(item)
    return item


@pytest.mark.parametrize("mode", ["irrelevant", "needs_review", "legacy", "pending", "expired", "withdrawn", "private"])
def test_only_active_current_policy_retail_candidates_email(store, filing, result, mode):
    if mode in ("irrelevant", "needs_review"):
        result["decision"] = mode
    if mode == "expired":
        result["action_deadline"] = "2000-01-01"
    if mode == "withdrawn":
        result["stage"] = mode
    if mode == "private":
        result["retail_accessible"] = False
    item = finish(store, filing, result)
    if mode == "legacy":
        item["state"]["result"].pop("policy")
    if mode == "pending":
        item["state"]["status"] = "pending"
    store.save(item)
    sent = []
    assert digest.dispatch(store, filing["day"], lambda: None, sent.append) == 0
    assert sent == []


@pytest.mark.parametrize("mode", ["legacy", "expired", "changed", "empty"])
def test_old_or_stale_outbox_cannot_send(store, filing, result, mode):
    item = finish(store, filing, result)
    message = digest.build_messages(store, filing["day"])[0]
    if mode == "legacy":
        message.pop("policy")
    if mode == "empty":
        message["versions"] = {}
    store.queue(message)
    if mode == "expired":
        item["state"]["result"]["findings"][0]["action_deadline"] = "2000-01-01"
    if mode == "changed":
        item["state"]["revision"] = "different"
    store.save(item)
    sent = []
    assert digest.deliver_pending(store, lambda: None, sent.append) == 0
    assert not sent and not store.pending_messages()
    persisted = json.loads(store.db.execute("SELECT data FROM messages").fetchone()[0])
    assert persisted["cancelled_at"] and persisted["cancel_reason"]


def test_weekly_digest_marks_all_source_days_dirty(store, filing, result):
    later = {**filing, "id": "other-day", "day": "2026-09-23", "published": "2026-09-23T12:00:00"}
    store.ingest(later["day"], [later], {})
    finish(store, filing, result)
    finish(store, later, result)
    messages = digest.build_messages(store, [filing["day"], later["day"]])
    assert len(messages) == 1 and len(messages[0]["versions"]) == 2
    store.queue(messages[0])
    store.changed_days.clear()
    store.message_sent(messages[0])
    assert store.changed_days == {filing["day"], later["day"]}
    assert not digest.build_messages(store, [filing["day"], later["day"]])


@pytest.mark.parametrize("no_text", [True, False])
def test_skipped_filings_make_zero_model_calls_and_stay_done(monkeypatch, store, filing, no_text):
    item = store.get(filing["id"])
    item["filing"].update(subject="Quarterly results", body="Ordinary sales and earnings.")
    doc = {"method": "no_text" if no_text else "text", "text": "" if no_text else "Ordinary financial results.",
           "pages": 1, "sparse_pages": [1] if no_text else [], "sha256": "abc"}
    monkeypatch.setattr(pipeline, "read_filing", lambda *a: doc)
    # No classify/cache_key methods: invoking the model would fail the test.
    c = SimpleNamespace(budget=Budget(1))
    processed = pipeline.process(item, Config(), c, time.monotonic() + 30)
    assert processed["state"]["status"] == "done"
    assert processed["state"]["skip_reason"] == ("no_text" if no_text else "no_catalyst_terms")
    store.save(processed)
    assert pipeline.screen_day(store, filing["day"], Config(), c)["processed"] == 0
    assert not digest.build_messages(store, filing["day"])


def test_keyword_gate_looks_beyond_headline(filing):
    f = {**filing, "subject": "Outcome of Board Meeting", "body": "Results approved"}
    assert classifier.has_catalyst(f, "\n" * 800 + "Tender buyback at Rs 120")
    assert not classifier.has_catalyst(f, "Normal operating results and dividend declared.")


@pytest.mark.parametrize("field,value", [("terms_quote", "invented price Rs 100"), ("retail_accessible", False),
    ("stage", "completed"), ("entry_exit", ""), ("action_deadline", "2026-02-31"), ("checks", [])])
def test_model_rejects_ungrounded_or_ineligible_positive(monkeypatch, filing, result, field, value):
    result[field] = value
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    def request(method, url, **kwargs):
        if method == "GET":
            return SimpleNamespace(json=lambda: {"data": [{"id": Config().model,
                "supported_parameters": ["reasoning", "response_format"],
                "pricing": {"prompt": "0.0000001", "completion": "0.0000005"}}]})
        return SimpleNamespace(json=lambda: {"usage": {"cost": .001}, "choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps(result)}}]})
    monkeypatch.setattr(classifier, "request", request)
    with pytest.raises(ValueError):
        Classifier(Config(), Budget(1)).classify(filing, "")


def test_expiry_is_checked_at_delivery_not_filing_date(store, filing, result):
    result["action_deadline"] = "2026-09-25"
    finish(store, filing, result)
    assert digest.build_messages(store, filing["day"], as_of=date(2026, 9, 25))
    assert not digest.build_messages(store, filing["day"], as_of=date(2026, 9, 26))


def test_collection_failure_persists_and_recovery_clears_it(store, filing):
    store.collection_failed(filing["day"], "403")
    store.collection_failed("2026-09-17", "403")
    assert store.metadata(filing["day"])["collection_error"] == "403"
    assert store.items(filing["day"])
    store.ingest(filing["day"], [filing], {})
    assert "collection_error" not in store.metadata(filing["day"])


def test_weekly_feed_failure_does_not_discard_other_days(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.Config, "from_env", lambda: Config(runtime=tmp_path))
    dates = [date(2026, 9, 17), date(2026, 9, 18)]
    monkeypatch.setattr(cli, "planned_dates", lambda *a: dates)
    calls = []
    def collect(day):
        calls.append(day)
        if day == dates[0]:
            raise RuntimeError("403")
        return [], {"expected": 0, "collected": 0, "pages": 1}
    monkeypatch.setattr(cli, "collect_day", collect)
    args = SimpleNamespace(workflow=False, send=False, date=None, max_filings=0, retry_errors=False)
    with pytest.raises(RuntimeError, match="Incomplete run"):
        cli.run(args)
    assert calls == dates
    s = Store(tmp_path / "state.sqlite3")
    assert s.metadata("2026-09-17")["collection_error"]
    assert s.metadata("2026-09-18")["collected"] == 0
    s.close()


def test_deployment_has_one_weekly_cron_and_no_ocr_packages():
    text = (Path(__file__).resolve().parents[1] / ".github/workflows/daily-digest.yml").read_text()
    assert text.count("cron:") == 1 and "cron: '17 2 * * 6'" in text
    assert "OPENROUTER_MODEL: openai/gpt-6-luna" in text and "REASONING_EFFORT: medium" in text
    assert "tesseract" not in text and "poppler" not in text and "MAX_OCR" not in text
