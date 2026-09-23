# Validation record

## Weekly retail-arbitrage migration — 2026-09-24

The historical broad-screen/OCR results below are not evidence of the new policy's
coverage. The model, screening policy, extraction behavior and schedule have changed.

- 72 regression tests pass locally, including native text/image PDF extraction without
  external binaries, zero-call no-text/local-filter skips, current-policy retail gates,
  deadline expiry, legacy/stale outbox cancellation, cross-day delivery checkpoints,
  weekly date coverage, failed-feed persistence, continued collection of other days,
  and the exact single weekly cron/model/reasoning deployment configuration.
- A live OpenRouter call returned `openai/gpt-6-luna` with requested medium reasoning
  and the new strict schema. A clearly labelled synthetic tender-buyback case was
  classified relevant, with quoted Rs 120 terms, participation deadline and explicit
  eligibility/acceptance/price checks. Cost: **$0.0003733**, 818 prompt/583 completion
  tokens. This was an isolated evaluation, never ingested or emailed as a real filing.
- Six previously downloaded real BSE PDFs were re-extracted natively. Niyogin's scheme
  notice (two sections) and Embassy's ordinary financing filing (one section) returned
  irrelevant. Rajeswari, JSW Dulux and Donear were rejected by the local text gate;
  Entero had no native text and was skipped. Three paid calls cost **$0.003355**.
  No OCR ran and no emails were sent. These cached PDFs test the new pipeline, not
  current feed availability. This is a small selected set, not a precision/recall study.
- The older scheduled runs
  [35878596535](https://github.com/amirahmedimtiaz/bse-special-situations/actions/runs/35878596535)
  and [35922969426](https://github.com/amirahmedimtiaz/bse-special-situations/actions/runs/35922969426)
  failed at BSE collection with HTTP 403. The same endpoint also returned 403 locally
  on 2026-09-24, including an ordinary browser-header/session warmup check. BSE's own
  current site configuration (`/assets/data/appConfig.json`) and public JS reference
  the same API host and `AnnSubCategoryGetData/w` endpoint. No alternative complete
  feed was substituted; access denials are not represented as zero announcements.

Hosted verification of this migration is recorded below when completed. Once-weekly
scheduling and the new code alone cannot guarantee upstream BSE access or exact timing.

## Historical validation — 2026-09-23

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

## Hosted testing and refinements

- GitHub smoke run [35828660754](https://github.com/amirahmedimtiaz/bse-special-situations/actions/runs/35828660754)
  collected all 1,191 announcements and attempted a deterministic 12-filing sample:
  11 completed, one evidence-validation error, and one successful real OCR extraction.
- Recovery run [35868850097](https://github.com/amirahmedimtiaz/bse-special-situations/actions/runs/35868850097)
  restored encrypted state and processed only that one failed filing. All 12 then
  completed; the other 11 required no repeated model calls.
- The first whole-day attempt exposed concurrent Tesseract CPU contention. It was
  cancelled before email delivery, retaining checkpoints. OCR was limited to two
  processes, one OpenMP thread per process and 2,400-pixel rendered pages.
  The three previously timed-out PDFs (Carraro India, Parshwanath Corporation and
  Evexia Lifecare) extracted successfully in a local concurrent test in 5.8–15.3 seconds;
  their hosted errors also cleared after restart.
- A manual review exposed false positives for ordinary secondary-market stake sales,
  normal NCD borrowing and mechanical stock splits. Prompt v2 explicitly distinguishes
  these from concrete control, distress, recapitalisation and restructuring events.
- A six-filing live v2 check excluded those three routine cases and retained Niyogin,
  Rajeswari and NDA Securities. Two initially rejected evidence responses were retried;
  only source-verified quotations are retained. Relevant results require at least one
  verified quotation. An unverified secondary quotation is discarded rather than published.
- Added tests cover changed-day-only checkpoints, retrying an unpushed commit, OCR
  resource bounds, historical prompt-change billing and stale-profile coverage.
  A 49-page scanned production filing also motivated an 80-page OCR cap with an
  eight-minute total per-document timeout. The latest local suite contains **50 passing tests**.

## Completed production verification

The deployment is a public repository using standard Ubuntu Actions runners; credentials
are GitHub Secrets and persisted results/outbox are encrypted on the `state` branch.

| Check | Observed result |
| --- | --- |
| Filing date | 2026-09-22, IST |
| Feed reconciliation | 1,191 announcements, 852 companies, 24 pages |
| Final screening coverage | 1,191 screened; zero processing errors; zero pending |
| AI candidate classifications | 167 relevant; 74 needs-review; 950 irrelevant |
| Extraction | 40 filings used local OCR; others used native text or supplied announcement metadata |
| Main full-day pass | 1,364 section calls; reported API cost $1.876539; earlier tests and recovery are additional |
| Final recovery pass | Two filings completed, including the 49-page scan; seven calls; $0.020133 |
| Delivery | Five initial digest parts and two recovery updates; completion email confirmed in inbox |
| Quiet rerun | Zero API calls, $0 additional API cost, zero emails |
| Regression suite | 50 tests passed locally and on the final hosted rerun |

Evidence: [main full-day run](https://github.com/amirahmedimtiaz/bse-special-situations/actions/runs/35870120122),
[final recovery](https://github.com/amirahmedimtiaz/bse-special-situations/actions/runs/35872506898),
[quiet rerun](https://github.com/amirahmedimtiaz/bse-special-situations/actions/runs/35872987220).
The delivered HTML of the first part was checked: 50 source links, company summaries and
coverage totals were present. The email remained unread; no mailbox labels were changed.

“Screened” means the automated processing completed, not that the model's interpretation
is guaranteed correct. The 74 needs-review items remain explicitly uncertain; many have
sparse pages in mixed text/image PDFs, which are not automatically OCRed under the chosen
text-first policy. Scheduled triggering is configured and active; manual hosted runs,
state recovery and inbox delivery were verified, not an exact-time scheduling guarantee.
