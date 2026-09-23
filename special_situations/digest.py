from __future__ import annotations

import html
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate

from .pipeline import coverage
from .store import fingerprint


def result_version(item):
    return fingerprint([item["state"]["revision"], item["state"].get("result")])


def build_messages(store, day, max_entries=50):
    items = store.items(day)
    counts = coverage(items)
    complete = counts["pending"] == 0 and counts["errors"] == 0
    eligible = [i for i in items if i["state"].get("result") and i["state"]["status"] != "pending"
                and (i["state"]["result"]["decision"] != "irrelevant" or i["state"].get("notified"))
                and i["state"].get("notified") != result_version(i)]
    eligible.sort(key=lambda i: (i["state"]["result"]["decision"] != "relevant", i["filing"]["company"],
                                 i["filing"]["published"], i["filing"]["id"]))
    if not eligible and store.already_reported(day, complete):
        return []
    groups = [eligible[n:n + max_entries] for n in range(0, len(eligible), max_entries)] or [[]]
    messages = []
    for n, group in enumerate(groups, 1):
        label = "complete" if complete else "PARTIAL — screening gaps remain"
        subject = f"BSE special situations | {day} | {label}"
        if len(groups) > 1:
            subject += f" | part {n}/{len(groups)}"
        intro = (f"BSE filing date: {day} (IST). Feed: {counts['total']} announcements; "
                 f"screened: {counts['screened']}; relevant: {counts['relevant']}; "
                 f"needs review: {counts['needs_review']}; failed: {counts['errors']}; "
                 f"pending: {counts['pending']}. OCR used for {counts['ocr']} filings. "
                 "New/updated items only; previously emailed items are not repeated.")
        fragments = ["<!doctype html><html><body style='font-family:Arial,sans-serif;line-height:1.5;max-width:960px'>",
                     f"<h1 style='font-size:22px'>{html.escape(subject)}</h1><p>{html.escape(intro)}</p>"]
        plain = [subject, intro]
        if not group:
            text = ("No new qualifying filings or review items." if complete else
                    "No new completed findings. Coverage is incomplete; unscreened filings are not negatives.")
            fragments.append(f"<p>{text}</p>")
            plain.append(text)
        for item in group:
            filing, state = item["filing"], item["state"]
            result = state["result"]
            heading = f"{filing['company']} ({filing['code']}) — {result['decision'].replace('_', ' ')}"
            link = state.get("document", {}).get("source_url") or filing["pdf_url"] or filing["page_url"]
            fragments.append(f"<section><h2 style='font-size:17px'>{html.escape(heading)}</h2>"
                             f"<p><a href='{html.escape(link, quote=True)}'>{html.escape(filing['subject']) or 'BSE filing'}</a>"
                             f"<br><small>{html.escape(filing['published'])} IST</small></p>")
            plain.extend(["", heading, filing["subject"], link])
            for finding in result["findings"][:3]:
                body = (f"{finding['category'].replace('_', ' ')} / {finding['stage'].replace('_', ' ')}: "
                        f"{finding['summary']} {finding['why_special']}")
                fragments.append(f"<p>{html.escape(body)}</p>")
                plain.append(body)
            if len(result["findings"]) > 3:
                note = "Additional section-level findings retained in saved results; see the full filing."
                fragments.append(f"<p>{note}</p>")
                plain.append(note)
            for warning in result["warnings"]:
                fragments.append(f"<p><strong>Review:</strong> {html.escape(warning)}</p>")
                plain.append("Review: " + warning)
            fragments.append("</section><hr>")
        footer = ("AI-assisted event discovery, not investment advice. Classification can miss or misread events; "
                  "check the original filing and transaction conditions. Text is extracted first; local English OCR "
                  "is used only when the entire PDF has no usable text. Mixed image/text gaps are flagged.")
        fragments.append(f"<p><small>{footer}</small></p></body></html>")
        plain.append(footer)
        versions = {i["filing"]["id"]: result_version(i) for i in group}
        mid = fingerprint([day, complete, counts, versions, n, len(groups)])
        messages.append({"id": mid, "day": day, "complete": complete, "versions": versions,
                         "subject": subject, "html": "\n".join(fragments), "text": "\n\n".join(plain)})
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
    pending = store.pending_messages()
    if pending:
        checkpoint()  # Do not send if the immutable outbox cannot be persisted.
    for message in pending:
        sender(message)
        store.message_sent(message)
        checkpoint()
    return len(pending)


def dispatch(store, day, checkpoint, sender=send_email):
    count = deliver_pending(store, checkpoint, sender)
    messages = build_messages(store, day)
    for message in messages:
        store.queue(message)
    return count + deliver_pending(store, checkpoint, sender)
