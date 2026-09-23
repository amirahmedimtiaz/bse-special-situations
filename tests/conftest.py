import pytest

from special_situations.bse import normalize
from special_situations.store import Store


@pytest.fixture
def row():
    return {"NEWSID": "abc-123", "SCRIP_CD": 500001, "DT_TM": "2026-09-22T14:00:00",
            "ATTACHMENTNAME": "abc.pdf", "SLONGNAME": "Example Ltd", "NEWSSUB": "Scheme update",
            "HEADLINE": "The board approved a scheme of demerger.", "CATEGORYNAME": "Company Update"}


@pytest.fixture
def filing(row):
    return normalize(row)


@pytest.fixture
def result():
    return {"decision": "relevant", "category": "demerger_spinoff", "stage": "board_approved",
            "summary": "The board approved a demerger scheme, subject to further approvals.",
            "why_special": "The scheme separates businesses.", "evidence": ["The board approved a scheme of demerger."]}


@pytest.fixture
def store(filing):
    value = Store(":memory:")
    value.ingest(filing["day"], [filing], {"expected": 1, "collected": 1, "pages": 1})
    yield value
    value.close()
