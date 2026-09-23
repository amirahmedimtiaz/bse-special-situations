# Implementation plan

Historical original plan below. Superseded on 2026-09-24 by the weekly, native-text-only,
GPT-6 Luna/medium retail-arbitrage implementation described in README.md. OCR, broad
special-situation/review emails, empty digests and daily backup triggers are removed.

1. Create an independent Python application for the whole BSE corporate-announcement
   feed. Collect every page for a complete IST date, check unique IDs against the
   exchange count, and retain date, company, source links and source metadata.
2. Download PDFs with bounded retries/size limits. Extract text locally first.
   Only if the entire filing yields no usable text, use local Tesseract OCR.
   Record extraction gaps, errors and page limits as review items; never turn them
   into confident negative classifications. No paid OCR service or PDF AI plugin.
3. Classify every filing with OpenRouter `openai/gpt-5.6-luna`, reasoning `high`.
   Use a versioned event taxonomy, strict JSON schema, verbatim evidence checks,
   bounded parallelism and chunking of long documents. Cache completed chunks.
   Track model usage/cost and distinguish relevant, irrelevant and needs-review.
4. Store work in SQLite. Export encrypted, compressed daily state partitions to
   a dedicated Git branch for recovery between free hosted runs. Keep API/email
   secrets and the encryption key out of Git. Persist before sending email.
5. Generate HTML/plain-text daily digests containing short event summaries and
   original BSE links. Include all relevant links, group updates sensibly, expose
   unreadable/unresolved coverage, and send a no-matches message on complete quiet
   days. Queue immutable digest messages so restart/retry does not rebuild sent mail.
6. Deploy to a public GitHub repository using standard Ubuntu Actions runners.
   Run after 07:00 IST and include backup schedule triggers. No always-running
   server, paid runner, paid database, or paid storage service. OpenRouter inference
   remains paid. GitHub schedule delays remain possible; persistent catch-up and
   repeated triggers reduce the consequences but cannot promise exact delivery time.
7. Test pagination, date/scope checks, download limits, extraction/OCR fallback,
   structured-output validation, evidence checking, idempotent retries, encrypted
   state round-trips, digest links/escaping, mail failures and checkpoint failures.
   Run bounded live BSE/PDF/model checks, a production smoke run, and verify persisted
   state and repeat-run behavior before handoff.

Default taxonomy: demergers/spin-offs; merger/arrangement; rights/recapitalization;
distress/insolvency/resolution; takeover/open offer/change of control; delisting;
buyback/capital return; significant business/asset sale; liquidation/distribution;
other unusual structural catalysts. Routine operating announcements and mechanical
compliance updates need context; a corporate event is not a buy recommendation.

Implementation should preserve explicit status (proposal, approval, conditions,
completion, withdrawal) and identify source limitations. Classifier recall is not
guaranteed by successful API calls. Mixed PDFs keep their available text and flag
image-only pages; OCR is deliberately limited to otherwise unreadable filings.
