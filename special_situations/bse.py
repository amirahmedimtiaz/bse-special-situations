from __future__ import annotations

from datetime import date
from urllib.parse import quote

from .network import request

API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
HEADERS = {"Referer": "https://www.bseindia.com/", "User-Agent": "bse-special-situations/0.1",
           "Accept": "application/json, text/plain, */*"}


def collect_day(day: date) -> tuple[list[dict], dict]:
    params = {"pageno": 1, "strCat": -1, "strPrevDate": day.strftime("%Y%m%d"), "strScrip": "",
              "strSearch": "P", "strToDate": day.strftime("%Y%m%d"), "strType": "C", "subcategory": -1}
    seen = {}
    counts = set()
    for page in range(1, 1001):
        params["pageno"] = page
        response = request("GET", API, params=params, headers=HEADERS)
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("Table"), list):
            raise ValueError("BSE response does not contain a valid Table")
        try:
            count = int(payload["Table1"][0]["ROWCNT"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError("BSE response is missing its total count") from exc
        counts.add(count)
        if len(counts) != 1:
            raise ValueError("BSE count changed during pagination; retry this date")
        before = len(seen)
        for row in payload["Table"]:
            if not isinstance(row, dict) or not row.get("NEWSID") or not row.get("SCRIP_CD"):
                raise ValueError("BSE row is missing announcement/company identity")
            if str(row.get("DT_TM", ""))[:10] != day.isoformat():
                raise ValueError("BSE returned a filing outside the requested date")
            seen[str(row["NEWSID"])] = normalize(row)
        if len(seen) == count:
            return list(seen.values()), {"expected": count, "collected": len(seen), "pages": page}
        if len(seen) > count or len(seen) == before:
            raise ValueError(f"BSE incomplete/inconsistent pagination: {len(seen)}/{count}")
    raise ValueError("BSE pagination limit exceeded")


def normalize(row: dict) -> dict:
    filename = str(row.get("ATTACHMENTNAME") or "")
    # Build URLs ourselves; never trust model-generated links.
    if filename and ("/" in filename or "\\" in filename or filename.startswith(".")):
        raise ValueError("Unexpected attachment filename")
    code = str(row["SCRIP_CD"])
    return {"id": str(row["NEWSID"]), "day": str(row["DT_TM"])[:10], "published": row["DT_TM"],
            "code": code, "company": str(row.get("SLONGNAME") or row.get("SLONGNAME1") or code),
            "subject": str(row.get("NEWSSUB") or ""),
            "body": str(row.get("HEADLINE") or row.get("MORE") or ""),
            "category": str(row.get("CATEGORYNAME") or ""), "attachment": filename,
            "pdf_url": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{quote(filename)}" if filename else "",
            "page_url": "https://www.bseindia.com/corporates/ann.html",
            "raw": row}
