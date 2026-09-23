# Validation record — 2026-09-23

## Before deployment

- 43 offline/integration tests passed locally. These include a real image-only PDF
  synthesized from a text document, rendered with Poppler and recovered with Tesseract.
  Text-bearing PDFs bypass OCR; mixed PDFs retain available text and flag sparse pages.
- All Python modules compiled; `pip check` reported no broken dependencies.
- Live BSE feed feasibility check: 1,191 unique announcements for 2026-09-22, matching
  the advertised count across 24 pages, covering 852 companies. This tests one day's
  feed availability, not long-term uptime or the classification of every filing.
- Live OpenRouter test using `openai/gpt-5.6-luna`, high reasoning: four real filings,
  five section-level calls, returned cost **$0.009587**. Results:

| Filing | Expected / observed |
| --- | --- |
| Niyogin Fintech, NCLT scheme update | Relevant; first-motion meeting directions, not final sanction |
| Rajeswari Infrastructure, generic Reg 30/42 heading | Relevant; resolution-plan capital restructuring and revised record date |
| NDA Securities, withdrawal | Relevant; cancellation of proposed preferential issue |
| Donear Industries, trading window | Irrelevant; routine compliance notice |

- The same local sample was rerun: zero filings reprocessed, no additional model calls.
- A PDF-signature validation defect found by live testing was fixed and covered by
  valid/invalid/oversize/archive-fallback download regression tests before deployment.

This small, deliberately chosen set checks plumbing and important stage distinctions.
It is **not** a measured precision/recall benchmark or a guarantee of all special situations
being discovered. Full production coverage and delivery are reported in Actions logs
and the daily email; failed/unreadable/pending filings remain visible.
