import pytest

from special_situations.bse import normalize
from special_situations.store import Store


@pytest.fixture
def row():
    return {"NEWSID": "abc-123", "SCRIP_CD": 500001, "DT_TM": "2026-09-22T14:00:00",
            "ATTACHMENTNAME": "abc.pdf", "SLONGNAME": "Example Ltd", "NEWSSUB": "Scheme update",
            "HEADLINE": "The board approved a tender buyback at Rs 120 per share.", "CATEGORYNAME": "Company Update"}


@pytest.fixture
def filing(row):
    return normalize(row)


@pytest.fixture
def result():
    return {"decision": "relevant", "category": "tender_buyback", "stage": "board_approved",
            "summary": "The board approved a tender buyback at Rs 120, subject to approvals.",
            "entry_exit": "Eligible public shareholders could tender shares for Rs 120, subject to acceptance.",
            "retail_accessible": True, "terms_quote": "tender buyback at Rs 120 per share.",
            "action_deadline": "", "deadline_quote": "",
            "checks": ["Check eligibility, live purchase price, costs and acceptance risk."],
            "evidence": ["The board approved a tender buyback at Rs 120 per share."]}


@pytest.fixture
def store(filing):
    value = Store(":memory:")
    value.ingest(filing["day"], [filing], {"expected": 1, "collected": 1, "pages": 1})
    yield value
    value.close()
