from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    runtime: Path = ROOT / ".runtime"
    model: str = "openai/gpt-5.6-luna"
    reasoning: str = "high"
    workers: int = 8
    max_run_usd: float = 10.0
    max_ocr_pages: int = 80
    max_pdf_mb: int = 30
    run_minutes: int = 150
    chunk_chars: int = 40000
    max_output_tokens: int = 6144

    @classmethod
    def from_env(cls):
        cfg = cls(runtime=Path(os.getenv("RUNTIME_DIR", str(ROOT / ".runtime"))),
                  model=os.getenv("OPENROUTER_MODEL", "openai/gpt-5.6-luna"),
                  reasoning=os.getenv("REASONING_EFFORT", "high"),
                  workers=int(os.getenv("WORKERS", "8")),
                  max_run_usd=float(os.getenv("MAX_RUN_USD", "10")),
                  max_ocr_pages=int(os.getenv("MAX_OCR_PAGES", "80")),
                  max_pdf_mb=int(os.getenv("MAX_PDF_MB", "30")),
                  run_minutes=int(os.getenv("RUN_MINUTES", "150")))
        if not 1 <= cfg.workers <= 16 or cfg.max_run_usd <= 0 or not 1 <= cfg.run_minutes <= 180:
            raise ValueError("Invalid worker, budget or runtime setting")
        return cfg
