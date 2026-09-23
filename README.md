# Weekly BSE retail-arbitrage candidates

BSE-wide corporate-announcement screening, independent of a company watchlist.
Uses OpenRouter **`openai/gpt-6-luna`**, reasoning **`medium`**. Emails contain only
filings with a plausible small-investor arbitrage mechanism, original links and short
summaries. No qualifying new filings means **no email**.

## Scope and safeguards

- Candidates need explicit numerical transaction terms, source-verified quotations
  and a potential retail entry/exit, exchange or entitlement mechanism. Examples:
  fixed-price tender buybacks/open offers, cash mergers, share exchanges, priced
  rights entitlements, delisting exits and unusual cash-outs. Mere restructuring,
  private QIPs, open-market buybacks, ordinary dividends/splits, operating updates
  and equity wipe-outs are not enough. Demergers need defined distribution terms
  and identifiable tradable legs, not merely an NCLT notice.
- **No live market-price feed or profitability calculation.** These are conditional
  research leads, not proven arbitrage or investment advice. Emails state missing
  eligibility, acceptance, liquidity/hedging, costs/taxes and completion checks.
  Do not assume a new buyer qualifies for a past record-date entitlement.
- Expired participation deadlines are suppressed at email delivery, when a deadline
  is stated in the filing. Unknown dates are not invented. Current deal status and
  later amendments still require verification; model interpretation can be wrong.
- No review-only, failure-only, empty or old broad-policy emails. Legacy/stale outbox
  messages are cancelled with a retained audit record before they can be sent.

## Processing and API-cost controls

1. Reconcile every page for each completed IST filing date against BSE's count;
   retain identity, timestamps, source metadata and original attachment links.
2. Download PDFs with size/time limits and extract native text with `pypdf`.
   **No OCR or vision calls.** PDFs with fewer than 40 non-whitespace characters
   are recorded as `no_text` and skipped without model calls. Mixed PDFs retain
   readable text and flag sparse/image pages. Metadata-only announcements can be
   screened if BSE supplied no attachment; an unreadable PDF is not silently replaced
   with a headline-only positive.
3. A broad local catalyst-keyword gate checks the **entire extracted text plus
   announcement metadata**, not only the headline. Filings with no matching terms
   incur zero model calls. This saves cost but can miss unusual wording; it is not
   exhaustive AI review of every announcement. Counts distinguish local filtering,
   no-text skips, failed work and pending work.
4. Send all available text of shortlisted filings in overlapping 60,000-character
   sections. Medium reasoning, compact negative JSON and a 3,072-token output/reasoning
   cap reduce API use. Do not truncate source documents to their first pages. Strict
   schema, literal evidence/terms checks and eligibility rules gate positive results.
5. Cache completed classifications and section responses. Reruns only process changed,
   unfinished or explicitly refreshed old-profile work. Completed older historical
   dates are not bulk-reclassified just because the model changed.
6. Persist SQLite state as compressed, encrypted stable ID-based shards on the `state`
   Git branch. Only changed days are rewritten. Raw PDFs, credentials, email addresses
   and plaintext classification results are not published.
7. Build one period digest, split into 50-entry parts only when needed. Each entry has
   its filing link, brief summary, possible mechanism, quoted terms and required checks.
   Previously emailed versions are not repeated. Persist the outbox before SMTP and
   checkpoint every source date's delivery state afterward.

The [OpenRouter model catalog](https://openrouter.ai/openai/gpt-6-luna) reported base
rates of **$0.10/million input tokens and $0.50/million output tokens** on 2026-09-24.
Prices may change; the app reads the live catalog and conservatively reserves for
retries and any higher context-price tiers. A **$10/run admission guard** is retained;
it is not a provider-enforced billing cap. Configure an OpenRouter key/account limit
as well. Failed ambiguous calls count conservatively toward the guard. No paid
PDF/OCR/search plugins are used. Actual weekly spend depends on filing volume, length,
shortlist rate and retries; the small live test is not a monthly-cost forecast.

## Free deployment and weekly schedule

Public repository, standard Ubuntu GitHub Actions runners, no hosted server or paid
database/storage service. Inference and any email-provider charges are separate.
See [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage).

**One scheduled run: Saturday 07:47 IST (02:17 UTC), cron `17 2 * * 6`.**
It reads the preceding seven completed IST dates, not just Friday. Missed dates,
recorded feed failures and unfinished older work are recovered in later runs.
There are no daily backup triggers. Manual dispatch remains available for testing
and recovery. The workflow filename remains `daily-digest.yml` for compatibility;
its display name and only cron are weekly. The separate Tests workflow has no
schedule and never sends emails or screens live filings.

Weekly screening can miss short offer windows. Filings posted late after their date
has left the refreshed window can also be missed. GitHub schedules may be delayed,
dropped or disabled after inactivity; see [schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
Silence means either no new candidates **or** a processing/feed problem: check Actions
and enable GitHub failure notifications. The application does not send failure emails.

BSE availability is external: HTTP 403 is surfaced as a collection failure, never
an empty day. Other dates continue, successful checkpoints survive, and the job exits
unsuccessfully if coverage is incomplete. No proxy or anti-bot bypass is included.
See [TESTING.md](TESTING.md) for current verification and known deployment limitations.

## Install and run

Requires Python 3.11+ and Git. No Poppler/Tesseract/system OCR packages.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp -n .env.example .env
# Fill .env securely; never commit it.
.venv/bin/python -m pytest -q
# One completed day, deterministic smoke sample, no email:
.venv/bin/python -m special_situations.cli --date 2026-09-22 --max-filings 12
# Previous seven completed days plus recovery:
.venv/bin/python -m special_situations.cli --send
```

Without `--send`, only ignored `output/weekly-YYYY-MM-DD-N.html` previews are generated
when candidates exist. Old preview files are historical artifacts, not current run
status. `--max-filings` cannot be combined with `--send`. Local state is ignored in
`.runtime/`; local commands do not change remote state unless `--workflow` is supplied.
Do not run two writers against the same runtime. Production uses one concurrency group.

## Credentials, deployment and recovery

GitHub Secrets: `OPENROUTER_API_KEY`, `EMAIL_SENDER`, `EMAIL_PASSWORD` (Gmail app
password), `EMAIL_RECEIVER`, `STATE_ENCRYPTION_KEY` (Fernet). The existing recipient
and encryption key are preserved during model/schedule updates.

```bash
# Initial configuration only; does not implicitly rotate an existing local state key:
.venv/bin/python scripts/configure_deployment.py --repo OWNER/REPO --email-env /path/to/email.env
gh workflow run daily-digest.yml --repo OWNER/REPO -f date=2026-09-22 -f max_filings=12 -f send=false
# Explicit recovery or whole-week run, with candidate-only delivery:
gh workflow run daily-digest.yml --repo OWNER/REPO -f max_filings=0 -f send=true
# Read-only encrypted state audit:
.venv/bin/python -m special_situations.audit --repo OWNER/REPO --errors
```

Keep the ignored mode-0600 `.env` backup safe. Losing/rotating the encryption key
without migration loses readable history/deduplication. The workflow token has
`contents: write` to checkpoint encrypted state, no separate personal token required.

Defaults: 8 workers, 150-minute runtime guard, 180-minute job timeout, 30 MB/PDF,
1,000 pages/PDF. Corrupt, encrypted, unsupported or oversized files remain logged
errors, not negative screens. Each filing has at most three failed attempts before
`--retry-errors` is needed. Budget/runtime-limited work remains pending. Checkpoints
occur every 40 processed filings and at day boundaries; hard termination may repeat
uncheckpointed calls. A crash after SMTP acceptance but before the next checkpoint
can duplicate mail; deterministic Message-ID is not an exactly-once guarantee.

State Git history grows and needs eventual archival. Metadata revisions trigger
re-screening; replacing a PDF at the same URL with unchanged metadata is not detected.
Scope is the BSE corporate-announcement feed, not all BSE webpages or NSE-only filings.
Filing content is untrusted data, not executable instructions. HTML is escaped; links
come from exchange metadata, never the model. Dependency/parser and upstream risks
cannot be eliminated. Regression tests cover the above policy, state and mail gates;
live paid calls are never part of pull-request tests.
