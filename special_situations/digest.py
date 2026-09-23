from __future__ import annotations

import html
import os
import smtplib
import ssl
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formatdate

from .classifier import PROMPT_VERSION
from .config import IST
from .pipeline import coverage
from .store import fingerprint


def result_version(item):
    return fingerprint([item["state"]["revision"], item["state"].get("result")])


def candidate_findings(item, as_of=None):
    as_of = as_of or datetime.now(IST).date()
    state = item["state"]
    result = state.get("result", {})
    if (state["status"] != "done" or result.get("policy") != PROMPT_VERSION
            or result.get("decision") != "relevant"):
        return []
    findings = []
    for finding in result.get("findings", []):
        if (finding.get("decision") != "relevant" or not finding.get("retail_accessible")
                or not finding.get("entry_exit") or not finding.get("terms_quote")
                or not finding.get("evidence") or not finding.get("checks")
                or finding.get("category") == "none"
                or finding.get("stage") in ("completed", "withdrawn", "not_applicable")):
            continue
        try:
            if finding.get("action_deadline") and date.fromisoformat(finding["action_deadline"]) < as_of:
                continue
        except ValueError:
            continue
        findings.append(finding)
    return findings


def build_messages(store, day, max_entries=50, as_of=None, collection_errors=None):
    days = sorted(set([day] if isinstance(day, str) else day))
    if not days:
        return []
    items = [i for d in days for i in store.items(d)]
    counts = coverage(items)
    missing = sorted(set(d for d in days if store.metadata(d) is None
                         or store.metadata(d).get("collection_error")) | set(collection_errors or []))
    complete = not missing and counts["pending"] == 0 and counts["errors"] == 0
    eligible = [i for i in items if candidate_findings(i, as_of)
                and i["state"].get("notified") != result_version(i)]
    eligible.sort(key=lambda i: (i["filing"]["company"], i["filing"]["published"], i["filing"]["id"]))
    # No empty, review-only, error-only or general special-situation email.
    if not eligible:
        return []
    groups = [eligible[n:n + max_entries] for n in range(0, len(eligible), max_entries)]
    messages = []
    period = days[0] if len(days) == 1 else f"{days[0]} to {days[-1]}"
    for n, group in enumerate(groups, 1):
        subject = f"BSE arbitrage candidates | {period}"
        if len(groups) > 1:
            subject += f" | part {n}/{len(groups)}"
        intro = (f"Filing dates: {period} (IST). {len(eligible)} new/updated candidate filings. "
                 f"Collected: {counts['total']}; processed: {counts['screened']}; "
                 f"local text filter: {counts['local_filtered']}; skipped without text: {counts['skipped_no_text']}; "
                 f"failed: {counts['errors']}; pending: {counts['pending']}. "
                 "These are conditional research leads, not verified profitable trades; live market prices are not checked.")
        if not complete:
            intro += " Coverage is PARTIAL; missing/failed work is not a negative result."
        if missing:
            intro += " Feed unavailable or not refreshed for: " + ", ".join(missing) + "."
        fragments = ["<!doctype html><html><body style='font-family:Arial,sans-serif;line-height:1.5;max-width:960px'>",
                     f"<h1 style='font-size:22px'>{html.escape(subject)}</h1><p>{html.escape(intro)}</p>"]
        plain = [subject, intro]
        for item in group:
            filing, state = item["filing"], item["state"]
            heading = f"{filing['company']} ({filing['code']})"
            link = state.get("document", {}).get("source_url") or filing["pdf_url"] or filing["page_url"]
            fragments.append(f"<section><h2 style='font-size:17px'>{html.escape(heading)}</h2>"
                             f"<p><a href='{html.escape(link, quote=True)}'>{html.escape(filing['subject']) or 'BSE filing'}</a>"
                             f"<br><small>{html.escape(filing['published'])} IST</small></p>")
            plain.extend(["", heading, filing["subject"], link])
            for finding in candidate_findings(item, as_of)[:3]:
                paragraphs = [f"{finding['category'].replace('_', ' ')} / {finding['stage'].replace('_', ' ')}: "
                              + finding["summary"],
                              "Possible mechanism: " + finding["entry_exit"],
                              "Filing terms: " + finding["terms_quote"],
                              "Check before acting: " + "; ".join(finding["checks"])]
                if finding.get("action_deadline"):
                    paragraphs.append("Stated participation deadline: " + finding["action_deadline"])
                for text in paragraphs:
                    fragments.append(f"<p>{html.escape(text)}</p>")
                    plain.append(text)
            for warning in state["result"].get("warnings", []):
                fragments.append(f"<p><strong>Limitation:</strong> {html.escape(warning)}</p>")
                plain.append("Limitation: " + warning)
            fragments.append("</section><hr>")
        footer = ("AI-assisted screening, not investment advice. Verify eligibility, live entry/exit prices, "
                  "acceptance, liquidity, costs/taxes and completion risk against the original filing. "
                  "Text extraction only: image-only filings are skipped, and image pages in mixed PDFs are not read. "
                  "A local keyword gate reduces API costs but can miss unusually worded opportunities. "
                  "Weekly screening can miss short offer windows; previously emailed versions are not repeated.")
        fragments.append(f"<p><small>{footer}</small></p></body></html>")
        plain.append(footer)
        versions = {i["filing"]["id"]: result_version(i) for i in group}
        mid = fingerprint([PROMPT_VERSION, days, versions, n, len(groups)])
        messages.append({"id": mid, "day": days[-1], "complete": complete, "versions": versions,
                         "policy": PROMPT_VERSION, "subject": subject,
                         "html": "\n".join(fragments), "text": "\n\n".join(plain)})
    return messages


def send_email(data):
    sender, password, receiver = (os.environ.get(k, "") for k in ("EMAIL_SENDER", "EMAIL_PASSWORD", "EMAIL_RECEIVER"))
    if not all((sender, password, receiver)):
        raise ValueError("Email sender, password and receiver must be configured")
    message = EmailMessage()
    message["Subject"] = data["subject"]
    message["From"] = sender
    message["To"] = receiver
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = f"<bse-special-{data['id']}@{sender.rsplit('@', 1)[-1]}>"
    message.set_content(data["text"])
    message.add_alternative(data["html"], subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=60) as smtp:
        smtp.login(sender, password)
        refused = smtp.send_message(message)
        if refused:
            raise RuntimeError("Email provider refused one or more recipients")


def deliver_pending(store, checkpoint, sender=send_email):
    count = 0
    for message in store.pending_messages():
        valid = message.get("policy") == PROMPT_VERSION and bool(message.get("versions"))
        for nid, version in message.get("versions", {}).items():
            item = store.get(nid)
            if (not item or not candidate_findings(item) or result_version(item) != version
                    or item["state"].get("notified") == version):
                valid = False
        if not valid:
            store.cancel_message(message, "Legacy policy, stale result, expired or no longer qualifying candidate")
            checkpoint()
            continue
        checkpoint()  # Never send unless the immutable outbox is durable.
        sender(message)
        store.message_sent(message)
        checkpoint()
        count += 1
    return count


def dispatch(store, day, checkpoint, sender=send_email, collection_errors=None):
    count = deliver_pending(store, checkpoint, sender)
    for message in build_messages(store, day, collection_errors=collection_errors):
        store.queue(message)
    return count + deliver_pending(store, checkpoint, sender)
