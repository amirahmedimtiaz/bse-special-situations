# BSE special-situations digest

A daily **BSE-wide** corporate-announcement screener, independent of any company watchlist.
It uses OpenRouter `openai/gpt-5.6-luna` with high reasoning and emails source-linked,
short summaries of corporate special situations. This is event discovery, not investment advice.

## How it works

1. Reconcile every page of BSE's corporate-announcement feed for a completed IST date
   against the exchange's advertised count. Preserve announcement identity and source metadata.
2. Extract PDF text locally. Only if the whole PDF has fewer than 40 non-whitespace
   text characters, fall back to local English Tesseract OCR. Mixed text/image PDFs
   keep the available text and flag sparse pages, without invoking OCR for every page.
3. Screen **every announcement**, not just keyword candidates. Split long text into
   overlapping sections; validate structured results and verbatim evidence quotes.
   Include proposals, approvals, record dates, updates, completions and withdrawals.
4. Save classification and per-section results in SQLite. Checkpoint encrypted,
   compressed per-day snapshots to the `state` Git branch. No raw PDFs, secrets,
   email addresses or plaintext screening results are published.
5. Send a digest with all newly qualifying filing links and brief summaries, followed
   by items needing review. Split large digests into 50-entry emails without dropping
   links. Errors and pending work appear in coverage totals, never as negative screens.

The taxonomy includes demergers/spinoffs, mergers/schemes, takeovers/control/open offers,
delistings, buybacks/material capital returns, consequential rights issues/recaps,
distress/insolvency/resolution, material asset/business transactions and liquidation.
Routine results, ordinary operating updates and boilerplate are normally excluded.
Ordinary NCD borrowing, secondary-market stake sales without a control/open-offer event,
mechanical stock splits/bonus issues and unspecific annual fundraising authorisations
are also excluded unless linked to a concrete restructuring or unusual cash-out event.

## Free hosting and schedule

The public repository uses **standard Ubuntu GitHub Actions runners**, which are free
for public repositories under [GitHub's current billing policy](https://docs.github.com/en/actions/concepts/billing-and-usage).
There is no hosted server, external database, paid OCR service or paid storage service.
OpenRouter inference and any email-provider charges are separate from hosting.

The primary trigger is **07:47 IST**, screening the previous completed IST day.
Backups run at 11:47, 15:47, 19:47 and 23:47 IST. Successful reruns do not resend the
same findings or repeat completed model calls. Two recent days are refreshed for late
postings, missed dates are caught up, and unfinished older dates are resumed.
Prompt/model changes re-screen refreshed dates, not every completed historical day;
an explicit `--date` can intentionally re-screen a past date under the new profile.

[GitHub schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
can be delayed/dropped and may be disabled after 60 days without qualifying repository
activity. Scheduled execution is not an uptime guarantee. Check Actions/your daily
email; enable GitHub workflow-failure notifications. If no digest arrives, run the
workflow manually and inspect its result. No always-on monitoring service is included.

## Install and run

Requires Python 3.11+, Git, Poppler (`pdftoppm`) and Tesseract (`eng`).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# Fill .env securely; never commit it.
.venv/bin/python -m pytest -q
.venv/bin/python -m special_situations.cli --date 2026-09-22 --max-filings 12
.venv/bin/python -m special_situations.cli --send
```

Without `--send`, the command only generates ignored `output/YYYY-MM-DD-N.html` previews.
`--max-filings` selects a deterministic sample and cannot be combined with `--send`.
Local state lives in ignored `.runtime/`; local runs do not change deployed state unless
`--workflow` and the remote/key configuration are supplied. Avoid concurrent local runs
sharing a runtime directory. Production uses a single-writer workflow concurrency group.

## Deploy

Create a public GitHub repository and push `main`. Set these GitHub Actions secrets:

| Secret | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | Paid inference via OpenRouter |
| `EMAIL_SENDER` | Gmail account sending the digest |
| `EMAIL_PASSWORD` | Gmail app password, not the normal account password |
| `EMAIL_RECEIVER` | Digest destination |
| `STATE_ENCRYPTION_KEY` | Fernet key protecting the persistent results/outbox |

For an existing local email configuration and an OpenRouter key in the environment:

```bash
.venv/bin/python scripts/configure_deployment.py --repo OWNER/REPO --email-env /path/to/email.env
gh workflow run daily-digest.yml --repo OWNER/REPO -f max_filings=12 -f send=false
gh workflow run daily-digest.yml --repo OWNER/REPO -f max_filings=0 -f send=true
```

Keep the generated ignored `.env` backup safe. Losing the encryption key loses access
to deduplication/history; do not simply rotate it. State pushes require the workflow
token's `contents: write` permission. No personal GitHub token is stored in this app.

Inspect deployed coverage and outbox status without sending email or modifying remote state:

```bash
.venv/bin/python -m special_situations.audit --repo OWNER/REPO --errors
```

## Limits and recovery

- Defaults: 8 workers, 150-minute run guard, 30 MB download cap, 1,000-page text cap,
  80-page image-only OCR cap, 40,000-character sections, 6,144 output/reasoning tokens.
  OCR has a separate two-process limit, single-threaded Tesseract and 2,400-pixel
  maximum rendered page dimension to avoid oversubscribing a free runner. Each OCR
  document has an eight-minute total time limit, including the wait for OCR capacity.
  Oversized, corrupt, encrypted, unsupported or unreadable attachments become review items.
- The $10/run admission guard reserves a conservative price estimate before each model
  call and records returned usage costs. Prices are read from the live model catalog.
  This is **not a provider-enforced billing cap**; set an OpenRouter key/account limit too.
  Ambiguous failed requests are charged against the guard conservatively. No web-search
  or paid PDF/OCR plugins are used. See [OpenRouter usage accounting](https://openrouter.ai/docs/guides/guides/usage-accounting).
- HTTP timeouts, bounded retries and backoff handle transient failures. Each filing gets
  at most three failed processing attempts before manual review; `--retry-errors` retries
  those cases after the underlying issue is resolved. Unprocessed budget/time-limited
  filings remain pending and are picked up by later triggers.
- Classification checkpoints occur every 40 processed filings and at day completion.
  Only changed days are serialized; stable ID-based encrypted shards avoid rewriting
  the entire historical dataset at every checkpoint.
  A hard runner termination can repeat uncheckpointed model calls. The immutable email
  outbox is persisted **before** sending and delivery state immediately afterward.
  A crash between SMTP acceptance and the subsequent checkpoint can duplicate a message;
  deterministic Message-ID helps but SMTP does not guarantee exactly-once delivery.
- Model success does not prove perfect recall or summary accuracy. Verbatim quotes are
  checked locally, but every semantic claim cannot be mechanically verified. Image/text
  gaps, metadata-only filings and ambiguous cases are visible. No claim of exhaustive
  investment-opportunity detection is made. Scope is BSE corporate announcements, not
  every document on every BSE webpage or NSE-only announcements.
- Persisted daily encrypted Git partitions avoid an external database, but Git history
  still grows. Monitor repository size and plan archival if usage approaches GitHub limits.
  A changed filing is re-screened when its headline/body/attachment/timestamp changes;
  same-URL PDF replacements with unchanged metadata are not automatically detected.

## Security and testing

Filing text is untrusted data, never instructions or executable code. Links come from
BSE metadata, not the AI. HTML is escaped. API/email credentials and the state key are
GitHub Secrets; local credentials are ignored and written with mode 0600. Standard
dependencies process exchange PDFs; malicious PDF/parser and upstream-availability risks
cannot be eliminated. Review dependencies periodically.

Offline tests cover pagination/count/date errors, extraction/OCR routing and limits,
chunk coverage, model schema/evidence, spending admission, caching/retries, encrypted
state round-trips, idempotent email, failure checkpoints, digest splitting/escaping and
catch-up dates. Live model calls are deliberately not part of pull-request tests.
See [PLAN.md](PLAN.md) for the initial implementation plan.
