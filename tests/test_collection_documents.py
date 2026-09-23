from datetime import date
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from special_situations import bse, documents, network
from special_situations.config import Config


def response(rows, count):
    return SimpleNamespace(json=lambda: {"Table": rows, "Table1": [{"ROWCNT": count}]})


def test_full_pagination(monkeypatch, row):
    other = {**row, "NEWSID": "second"}
    calls = []
    pages = iter([response([row], 2), response([other], 2)])
    def fetch(*args, **kwargs):
        calls.append(kwargs["params"].copy())
        return next(pages)
    monkeypatch.setattr(bse, "request", fetch)
    rows, counts = bse.collect_day(date(2026, 9, 22))
    assert counts == {"collected": 2, "expected": 2, "pages": 2}
    assert len(rows) == 2
    assert [c["pageno"] for c in calls] == [1, 2]
    assert all(c["strScrip"] == "" for c in calls)


@pytest.mark.parametrize("kind", ["wrong_date", "duplicate", "changed_count", "missing_count", "html"])
def test_bad_feeds_fail_closed(monkeypatch, row, kind):
    first = response([row], 2)
    if kind == "wrong_date":
        first = response([{**row, "DT_TM": "2026-09-21"}], 1)
    second = response([row], 2)
    if kind == "changed_count":
        second = response([{**row, "NEWSID": "new"}], 3)
    if kind == "missing_count":
        first = SimpleNamespace(json=lambda: {"Table": []})
    if kind == "html":
        first = SimpleNamespace(json=lambda: "<html>blocked</html>")
    pages = iter([first, second])
    monkeypatch.setattr(bse, "request", lambda *a, **k: next(pages))
    with pytest.raises(ValueError):
        bse.collect_day(date(2026, 9, 22))


def test_zero_day(monkeypatch):
    monkeypatch.setattr(bse, "request", lambda *a, **k: response([], 0))
    assert bse.collect_day(date(2026, 9, 22))[1]["collected"] == 0


@pytest.mark.parametrize("filename", ["../x.pdf", "a/b.pdf", "a\\b.pdf", ".private"])
def test_unsafe_attachment(row, filename):
    with pytest.raises(ValueError):
        bse.normalize({**row, "ATTACHMENTNAME": filename})


def test_nonpdf_kept_as_review_candidate(row):
    f = bse.normalize({**row, "ATTACHMENTNAME": "data.zip"})
    with pytest.raises(ValueError, match="Non-PDF"):
        documents.read_filing(f, Config())


def test_no_attachment_metadata(filing):
    assert documents.read_filing({**filing, "attachment": ""}, Config())["method"] == "metadata_only"


def test_text_never_ocr(monkeypatch, tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"test")
    monkeypatch.setattr(documents, "PdfReader", lambda _: SimpleNamespace(is_encrypted=False,
        pages=[SimpleNamespace(extract_text=lambda: "This is a readable filing with sufficient ordinary text."),
               SimpleNamespace(extract_text=lambda: "")]))
    monkeypatch.setattr(documents, "ocr_pdf", lambda *a: pytest.fail("Mixed PDF must not invoke OCR"))
    data = documents.extract(source, Config())
    assert data["method"] == "text" and data["sparse_pages"] == [2]


def test_no_text_uses_ocr(monkeypatch, tmp_path):
    source = tmp_path / "empty.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(source)
    calls = []
    def fake_ocr(*args):
        calls.append(args)
        return ["The board approved a demerger, subject to regulatory and shareholder approvals."]
    monkeypatch.setattr(documents, "ocr_pdf", fake_ocr)
    data = documents.extract(source, Config())
    assert data["method"] == "ocr" and len(calls) == 1


def test_ocr_limit(tmp_path):
    with pytest.raises(ValueError, match="OCR limit"):
        documents.ocr_pdf(tmp_path / "x.pdf", 41, Config())


def test_ocr_bounds_cpu_and_pixels(monkeypatch, tmp_path):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="Extracted text")
    monkeypatch.setattr(documents.subprocess, "run", run)
    assert documents.ocr_pdf(tmp_path / "x.pdf", 1, Config()) == ["Extracted text"]
    assert calls[0][0][calls[0][0].index("-scale-to") + 1] == "2400"
    assert calls[1][1]["env"]["OMP_THREAD_LIMIT"] == "1"


def test_chunk_boundaries():
    text = "".join(chr(0x3000 + i) for i in range(10000))
    chunks = documents.chunks(text, 2000)
    assert chunks[0] + "".join(c[500:] for c in chunks[1:]) == text
    assert max(map(len, chunks)) <= 2000
    assert documents.chunks("", 2000) == [""]


def test_network_preserves_timeout_on_retry(monkeypatch):
    calls = []
    statuses = iter([429, 200])
    def request(*a, **k):
        calls.append(k)
        return SimpleNamespace(status_code=next(statuses), headers={}, close=lambda: None,
                               raise_for_status=lambda: None)
    monkeypatch.setattr(network, "session", lambda: SimpleNamespace(request=request))
    monkeypatch.setattr(network.time, "sleep", lambda _: network._next.clear())
    network.request("GET", "https://example.test", timeout=(1, 7))
    assert [c["timeout"] for c in calls] == [(1, 7), (1, 7)]


@pytest.mark.parametrize("kind", ["valid", "html", "oversize", "archive_fallback"])
def test_download_validation(monkeypatch, filing, tmp_path, kind):
    calls = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def iter_content(self, _):
            yield b"html" if kind == "html" else b"%PDF-1.7\nmock data"
    def fetch(method, url, **kwargs):
        calls.append(url)
        if kind == "archive_fallback" and "AttachLive" in url:
            raise RuntimeError("live attachment moved")
        return Response()
    monkeypatch.setattr(documents, "request", fetch)
    cfg = Config(runtime=tmp_path, max_pdf_mb=0 if kind == "oversize" else 1)
    if kind in ("html", "oversize"):
        with pytest.raises(RuntimeError):
            documents.download(filing, cfg)
        assert not list(tmp_path.rglob("*.part"))
    else:
        path = documents.download(filing, cfg)
        assert path.read_bytes().startswith(b"%PDF-")
        before = len(calls)
        assert documents.download(filing, cfg) == path and len(calls) == before
        assert len(calls) == (2 if kind == "archive_fallback" else 1)
        if kind == "archive_fallback":
            assert "AttachHis" in filing["resolved_pdf_url"]
