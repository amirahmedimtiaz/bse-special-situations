import json
import subprocess
import time
from datetime import date
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet, InvalidToken

from special_situations import classifier, digest, pipeline
from special_situations.classifier import Budget, BudgetExceeded, Classifier, combine
from special_situations.cli import planned_dates
from special_situations.config import Config
from special_situations.state_sync import StateSync
from special_situations.store import Store, fingerprint


def finished(store, filing, result):
    item = store.get(filing["id"])
    item["state"].update(status="done", result={"decision": result["decision"], "findings": [result], "warnings": []})
    store.save(item)
    return item


def test_budget_reserves_concurrently():
    b = Budget(1)
    b.reserve(.6)
    with pytest.raises(BudgetExceeded):
        b.reserve(.5)
    b.settle(.6, .2)
    b.reserve(.7)
    assert b.spent == .2 and b.calls == 1


@pytest.mark.parametrize("mode", ["valid", "mixed_quotes", "missing_quote", "fabricated_quote", "bad_schema", "truncated"])
def test_model_contract(monkeypatch, filing, result, mode):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    seen = []
    result = dict(result)
    if mode == "missing_quote":
        result["evidence"] = []
    if mode == "fabricated_quote":
        result["evidence"] = ["This evidence is invented"]
    if mode == "mixed_quotes":
        result["evidence"] = [*result["evidence"], "This secondary quote is invented"]
    if mode == "bad_schema":
        result["extra"] = True
    def request(method, url, **kwargs):
        seen.append(kwargs)
        if method == "GET":
            return SimpleNamespace(json=lambda: {"data": [{"id": Config().model,
                "supported_parameters": ["reasoning", "response_format"],
                "pricing": {"prompt": "0.0000002", "completion": "0.0000012"}}]})
        return SimpleNamespace(json=lambda: {"model": Config().model, "usage": {"cost": .001}, "choices": [{
            "finish_reason": "length" if mode == "truncated" else "stop",
            "message": {"content": json.dumps(result)}}]})
    monkeypatch.setattr(classifier, "request", request)
    b = Budget(1)
    c = Classifier(Config(), b)
    if mode in ("valid", "mixed_quotes"):
        output = c.classify(filing, "")
        assert output["result"]["evidence"] == ["The board approved a scheme of demerger."]
        assert output["evidence_validation"]["rejected"] == (1 if mode == "mixed_quotes" else 0)
    else:
        with pytest.raises(Exception):
            c.classify(filing, "")
    assert b.spent == .001 and b.reserved == pytest.approx(0)
    assert seen[-1]["json"]["reasoning"] == {"effort": "high"}


def test_partial_text_cannot_be_confident_negative(result):
    result["decision"] = "irrelevant"
    data = combine([result], {"method": "text", "sparse_pages": [2]})
    assert data["decision"] == "needs_review" and data["warnings"]


def test_relevant_retained_with_gap(result):
    assert combine([result], {"method": "text", "sparse_pages": [2]})["decision"] == "relevant"


def test_store_preserves_seen_and_resets_revision(store, filing, result):
    finished(store, filing, result)
    store.ingest(filing["day"], [filing], {})
    assert store.get(filing["id"])["state"]["status"] == "done"
    store.ingest(filing["day"], [{**filing, "subject": "Corrected scheme"}], {})
    assert store.get(filing["id"])["state"]["status"] == "pending"
    with pytest.raises(ValueError, match="disappeared"):
        store.ingest(filing["day"], [], {})


def test_snapshot_roundtrip(store, filing, result):
    finished(store, filing, result)
    message = digest.build_messages(store, filing["day"])[0]
    store.queue(message)
    store.message_sent(message)
    fresh = Store(":memory:")
    for _, snapshot in store.partitions():
        fresh.restore(snapshot)
    assert list(fresh.partitions()) == list(store.partitions())
    assert digest.build_messages(fresh, filing["day"]) == []


def test_encrypted_remote_roundtrip(tmp_path, store):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    key = Fernet.generate_key().decode()
    one = StateSync(tmp_path / "one", str(remote), key)
    one.save(store)
    before = one.git("rev-parse", "HEAD")
    one.save(store)
    assert one.git("rev-parse", "HEAD") == before
    assert b"Example Ltd" not in next((tmp_path / "one").glob("*.enc")).read_bytes()
    two = StateSync(tmp_path / "two", str(remote), key)
    fresh = Store(":memory:")
    two.restore(fresh)
    assert fresh.items("2026-09-22") == store.items("2026-09-22")
    two.fernet = Fernet(Fernet.generate_key())
    with pytest.raises(InvalidToken):
        two.restore(fresh)


def test_retry_uses_cached_chunks(monkeypatch, store, filing, result):
    cfg = Config(chunk_chars=1000, workers=1)
    monkeypatch.setattr(pipeline, "read_filing", lambda *a: {"text": "x" * 1800, "method": "text", "pages": 1,
                         "sparse_pages": [], "sha256": "hash"})
    calls = []
    fail = [True]
    def classify(filing, text):
        calls.append(text)
        if len(calls) == 2 and fail[0]:
            raise RuntimeError("temporary API error")
        return {"result": result}
    c = SimpleNamespace(cache_key=lambda f, t: fingerprint(t), classify=classify, budget=Budget(1))
    stats = pipeline.screen_day(store, filing["day"], cfg, c)
    assert stats["coverage"]["errors"] == 1
    fail[0] = False
    pipeline.screen_day(store, filing["day"], cfg, c)
    assert len(calls) == 3
    pipeline.screen_day(store, filing["day"], cfg, c)
    assert len(calls) == 3
    assert store.get(filing["id"])["state"]["status"] == "done"


def test_budget_failure_retains_pending(monkeypatch, store, filing):
    monkeypatch.setattr(pipeline, "read_filing", lambda *a: (_ for _ in ()).throw(BudgetExceeded("limit")))
    c = SimpleNamespace(budget=Budget(1))
    pipeline.screen_day(store, filing["day"], Config(workers=1), c)
    state = store.get(filing["id"])["state"]
    assert state["status"] == "pending" and state["attempts"] == 0


def test_deadline_skips_calls(store, filing):
    stats = pipeline.screen_day(store, filing["day"], Config(), SimpleNamespace(budget=Budget(1)),
                                deadline=time.monotonic() - 1)
    assert stats["processed"] == 0


def test_historical_completed_days_do_not_rebill_after_prompt_change(store, filing, result):
    item = finished(store, filing, result)
    item["state"]["profile"] = "old-prompt-version"
    store.save(item)
    stats = pipeline.screen_day(store, filing["day"], Config(), SimpleNamespace(budget=Budget(1)), reclassify=False)
    assert stats["processed"] == 0


def test_digest_escape_and_no_duplicates(store, filing, result):
    result["summary"] = "<script>alert('bad')</script>"
    finished(store, filing, result)
    sent = []
    assert digest.dispatch(store, filing["day"], lambda: None, sent.append) == 1
    assert "<script>" not in sent[0]["html"] and "&lt;script&gt;" in sent[0]["html"]
    assert filing["pdf_url"] in sent[0]["html"]
    assert digest.dispatch(store, filing["day"], lambda: None, sent.append) == 0


def test_failed_email_is_retried_unchanged(store, filing, result):
    finished(store, filing, result)
    def fail(_):
        raise RuntimeError("mail unavailable")
    with pytest.raises(RuntimeError):
        digest.dispatch(store, filing["day"], lambda: None, fail)
    queued = store.pending_messages()
    sent = []
    digest.dispatch(store, filing["day"], lambda: None, sent.append)
    assert sent == queued and not store.pending_messages()


def test_checkpoint_failure_prevents_mail(store, filing, result):
    finished(store, filing, result)
    sent = []
    def fail():
        raise RuntimeError("cannot persist")
    with pytest.raises(RuntimeError):
        digest.dispatch(store, filing["day"], fail, sent.append)
    assert not sent


def test_digest_split_keeps_every_link(store, filing, result):
    rows = [{**filing, "id": str(n), "pdf_url": f"https://www.bseindia.com/{n}.pdf"} for n in range(105)]
    rows.append(filing)
    store.ingest(filing["day"], rows, {})
    for row in rows:
        finished(store, row, result)
    messages = digest.build_messages(store, filing["day"])
    assert len(messages) == 3
    assert sum(len(m["versions"]) for m in messages) == 106
    for row in rows:
        assert sum(row["pdf_url"] in m["html"] for m in messages) == 1


def test_empty_completed_day_emails_once():
    store = Store(":memory:")
    store.ingest("2026-09-22", [], {"expected": 0})
    sent = []
    digest.dispatch(store, "2026-09-22", lambda: None, sent.append)
    digest.dispatch(store, "2026-09-22", lambda: None, sent.append)
    assert len(sent) == 1 and sent[0]["complete"]


def test_catchup_dates():
    assert planned_dates([], date(2026, 9, 22)) == [date(2026, 9, 22)]
    assert planned_dates(["2026-09-18"], date(2026, 9, 22)) == [date(2026, 9, d) for d in range(18, 23)]
    assert planned_dates(["2026-09-18", "2026-09-22"], date(2026, 9, 22)) == [date(2026, 9, 21), date(2026, 9, 22)]


def test_checkpoint_only_serializes_dirty_days(store, filing, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    sync = StateSync(tmp_path / "copy", str(remote), Fernet.generate_key().decode())
    sync.save(store)
    assert not store.changed_days
    store.ingest("2026-09-23", [], {"expected": 0})
    assert [day for day, _ in store.partitions(store.changed_days)] == ["2026-09-23"]
    sync.save(store)
    assert not store.changed_days
    item = store.get(filing["id"])
    store.save(item)
    assert store.changed_days == {filing["day"]}


def test_failed_push_is_retried_even_when_files_unchanged(monkeypatch, store, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    sync = StateSync(tmp_path / "copy", str(remote), Fernet.generate_key().decode())
    original = sync.git
    def fail_push(*args):
        if args[0] == "push":
            raise subprocess.CalledProcessError(1, "git push")
        return original(*args)
    monkeypatch.setattr(sync, "git", fail_push)
    monkeypatch.setattr("special_situations.state_sync.time.sleep", lambda _: None)
    with pytest.raises(subprocess.CalledProcessError):
        sync.save(store)
    assert sync.pending_push and store.changed_days
    monkeypatch.setattr(sync, "git", original)
    sync.save(store)
    assert not sync.pending_push and not store.changed_days
    assert original("ls-remote", "--heads", "origin", "state").strip()
