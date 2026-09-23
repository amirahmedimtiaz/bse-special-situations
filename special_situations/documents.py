from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from pypdf import PdfReader

from .bse import HEADERS
from .config import Config
from .network import request

def download(filing: dict, cfg: Config) -> Path:
    folder = cfg.runtime / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    if Path(filing["attachment"]).name != filing["attachment"]:
        raise ValueError("Unsafe attachment name")
    path = folder / filing["attachment"]
    if path.exists():
        link_file = path.with_suffix(".url")
        filing["resolved_pdf_url"] = link_file.read_text() if link_file.exists() else filing["pdf_url"]
        return path
    failures = []
    for archive in ("AttachLive", "AttachHis"):
        url = filing["pdf_url"].replace("AttachLive", archive)
        try:
            response = request("GET", url, headers=HEADERS, stream=True, timeout=(10, 40))
            temporary = path.with_suffix(f".{uuid.uuid4().hex}.part")
            size = 0
            with response, temporary.open("wb") as output:
                for block in response.iter_content(65536):
                    size += len(block)
                    if size > cfg.max_pdf_mb * 1024 * 1024:
                        raise ValueError("PDF exceeds configured download size limit")
                    output.write(block)
            with temporary.open("rb") as source:
                if source.read(5) != b"%PDF-":
                    raise ValueError("Attachment response is not a PDF")
            temporary.replace(path)
            path.with_suffix(".url").write_text(url)
            filing["resolved_pdf_url"] = url
            return path
        except Exception as exc:
            failures.append(f"{archive}: {type(exc).__name__}: {exc}")
        finally:
            if "temporary" in locals():
                temporary.unlink(missing_ok=True)
    raise RuntimeError("Unable to retrieve PDF: " + "; ".join(failures))


def extract(path: Path, cfg: Config) -> dict:
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("Encrypted PDF cannot be read")
    if len(reader.pages) > 1000:
        raise ValueError("PDF exceeds 1,000-page extraction limit")
    texts = [page.extract_text() or "" for page in reader.pages]
    method = "text"
    if sum(len(re.sub(r"\s", "", t)) for t in texts) < 40:
        method = "no_text"
    gaps = [i + 1 for i, text in enumerate(texts) if len(text.strip()) < 20]
    content = "\n\n".join(f"[PDF page {i + 1}]\n{text}" for i, text in enumerate(texts)) if method == "text" else ""
    return {"text": content, "method": method, "pages": len(texts), "sparse_pages": gaps,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read_filing(filing: dict, cfg: Config) -> dict:
    if not filing["attachment"]:
        return {"text": "", "method": "metadata_only", "pages": 0, "sparse_pages": [], "sha256": ""}
    if not filing["attachment"].lower().endswith(".pdf"):
        raise ValueError("Non-PDF attachment requires manual review")
    result = extract(download(filing, cfg), cfg)
    result["source_url"] = filing.get("resolved_pdf_url", filing["pdf_url"])
    return result


def chunks(text: str, size: int) -> list[str]:
    # All characters are retained; a small overlap preserves boundary context.
    if not text:
        return [""]
    if size < 1000:
        raise ValueError("Chunk size is too small")
    result = []
    start = 0
    while start < len(text):
        result.append(text[start:start + size])
        if start + size >= len(text):
            break
        start += size - 500
    return result
