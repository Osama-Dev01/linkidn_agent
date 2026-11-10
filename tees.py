import email
import imaplib
import os
import re
import smtplib
import ssl
import time
import uuid
from datetime import date, timedelta
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

from dotenv import load_dotenv

load_dotenv()

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
QUOTE_START = re.compile(r"^(>|On .+ wrote:|-{2,}\s*Original Message|From:)", re.I)


# ---------- sending ----------

def send_email(to: str, subject: str, html: str, text: str = "") -> str:
    """Send an email and return its Message-ID (used to match replies)."""
    msg = EmailMessage()
    message_id = make_msgid(domain="linkedin-agent.local")
    msg["Message-ID"] = message_id
    msg["From"] = os.environ["GMAIL_ADDRESS"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text or "Open this email in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as server:
        server.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        server.send_message(msg)
    return message_id


# ---------- receiving ----------

def _body_text(msg: email.message.Message) -> str:
    """Extract plain text from a message (falls back to stripped HTML)."""
    plain, html = "", ""
    for part in msg.walk():
        if part.is_multipart() or "attachment" in str(part.get("Content-Disposition", "")):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_type() == "text/plain" and not plain:
            plain = text
        elif part.get_content_type() == "text/html" and not html:
            html = text
    return plain or re.sub(r"<[^>]+>", " ", html)


def _strip_quoted(text: str) -> str:
    """Keep only what the user typed, dropping the quoted original."""
    lines = []
    for line in text.splitlines():
        if QUOTE_START.match(line.strip()):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _imap_date(d: date) -> str:
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"


def fetch_reply(message_id: str, my_address: str, allowed_sender: str) -> dict | None:
    """Return the first matching reply to `message_id`, or None."""
    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(my_address, os.environ["GMAIL_APP_PASSWORD"])
        imap.select("INBOX")

        since = _imap_date(date.today() - timedelta(days=1))
        _, data = imap.search(None, "SINCE", since)

        for num in reversed(data[0].split()):
            # peek at headers only (does not mark the message as read)
            _, hdr_data = imap.fetch(
                num, "(BODY.PEEK[HEADER.FIELDS (IN-REPLY-TO REFERENCES FROM SUBJECT)])"
            )
            headers = email.message_from_bytes(hdr_data[0][1])
            refs = f"{headers.get('In-Reply-To', '')} {headers.get('References', '')}"
            if message_id not in refs:
                continue

            sender = parseaddr(headers.get("From", ""))[1].lower()
            if sender != allowed_sender:
                continue

            _, full = imap.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(full[0][1])
            return {
                "from": sender,
                "subject": msg.get("Subject", ""),
                "raw_body": _body_text(msg),
                "reply": _strip_quoted(_body_text(msg)),
            }
    return None


def wait_for_reply(message_id: str, timeout_s: int = 600, poll_s: int = 10) -> dict | None:
    address = os.environ["GMAIL_ADDRESS"]
    allowed = os.environ.get("NOTIFY_EMAIL", address).lower()
    deadline = time.time() + timeout_s

    print(f"Waiting for your reply (up to {timeout_s // 60} min)... reply to the email now.")
    while time.time() < deadline:
        try:
            result = fetch_reply(message_id, address, allowed)
            if result:
                return result
        except Exception as exc:
            print("poll error:", exc)
        time.sleep(poll_s)
    return None


# ---------- demo ----------

def main() -> None:
    to = os.environ.get("NOTIFY_EMAIL", os.environ["GMAIL_ADDRESS"])
    run_id = uuid.uuid4().hex[:8]

    topics = [
        {"title": "Lessons from building a LangGraph agent", "url": "http://localhost:8000/select?t=1"},
        {"title": "Why structured outputs matter for LLM pipelines", "url": "http://localhost:8000/select?t=2"},
        {"title": "Human-in-the-loop patterns for AI agents", "url": "http://localhost:8000/select?t=3"},
    ]

    items = "".join(
        f'<li style="margin-bottom:10px"><a href="{t["url"]}">{t["title"]}</a></li>'
        for t in topics
    )
    html = f"""
    <div style="font-family:Arial,sans-serif">
      <h2>Pick your next LinkedIn topic</h2>
      <ol>{items}</ol>
      <p>Or just reply to this email with the number (1, 2 or 3), or "none" plus what you want instead.</p>
    </div>
    """
    text = (
        "Pick your next LinkedIn topic:\n"
        + "\n".join(f"{i}. {t['title']} - {t['url']}" for i, t in enumerate(topics, 1))
        + "\n\nReply with the number (1, 2 or 3), or 'none' plus what you want instead."
    )

    message_id = send_email(to, f"Pick your next LinkedIn topic [run:{run_id}]", html, text)
    print(f"Email sent to {to} (run {run_id})")

    result = wait_for_reply(message_id)
    if result is None:
        print("No reply received before timeout.")
        return

    print("\n--- Reply received ---")
    print("From:   ", result["from"])
    print("Subject:", result["subject"])
    print("Reply:  ", repr(result["reply"]))


if __name__ == "__main__":
    main()