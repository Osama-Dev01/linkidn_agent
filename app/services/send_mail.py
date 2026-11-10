import email
import imaplib
import logging
import os
import re
import smtplib
import ssl
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from html import escape, unescape
from uuid import uuid4

from langgraph.types import interrupt

from app.autonomous.writer_schema import VersionedDraft
from app.autonomous.supervisor import review_is_current
from app.db.client import get_database
from app.db.schema import FeedbackEvent
from app.graph.state import ResearchState, Topic


logger = logging.getLogger(__name__)
QUOTE_START = re.compile(r"^(>|On .+ wrote:|-{2,}\s*Original Message|From:)", re.I)


def send_email(to: str, subject: str, html: str, text: str, attempts: int = 3) -> str:
    message = EmailMessage()
    message_id = make_msgid(domain="linkedin-agent.local")
    message["Message-ID"] = message_id
    message["From"] = os.environ["GMAIL_ADDRESS"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    for attempt in range(1, attempts + 1):
        try:
            with smtplib.SMTP_SSL(
                "smtp.gmail.com", 465, timeout=20, context=ssl.create_default_context()
            ) as server:
                server.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
                server.send_message(message)
            return message_id
        except (OSError, smtplib.SMTPException) as error:
            logger.warning("SMTP attempt %d/%d failed: %s", attempt, attempts, error)
            if attempt == attempts:
                raise
            time.sleep(2 ** attempt)


def _body_text(message: email.message.Message) -> str:
    plain, html = "", ""
    for part in message.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_type() == "text/plain" and not plain:
            plain = text
        elif part.get_content_type() == "text/html" and not html:
            html = text
    html = re.sub(r"<(?:br\s*/?|/p|/div)>", "\n", html, flags=re.I)
    return plain or unescape(re.sub(r"<[^>]+>", " ", html))


def _strip_quoted(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if QUOTE_START.match(line.strip()):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def fetch_reply(message_id: str, allowed_sender: str, ignored_ids: set[str]) -> dict | None:
    with imaplib.IMAP4_SSL("imap.gmail.com") as mailbox:
        mailbox.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        mailbox.select("INBOX", readonly=True)
        _, data = mailbox.search(
            None, "OR", "HEADER", "In-Reply-To", f'"{message_id}"',
            "HEADER", "References", f'"{message_id}"',
        )
        for number in reversed(data[0].split()):
            _, headers_data = mailbox.fetch(
                number, "(BODY.PEEK[HEADER.FIELDS (IN-REPLY-TO REFERENCES FROM MESSAGE-ID)])"
            )
            headers = email.message_from_bytes(headers_data[0][1])
            references = f"{headers.get('In-Reply-To', '')} {headers.get('References', '')}"
            sender = parseaddr(headers.get("From", ""))[1].casefold()
            reply_id = headers.get("Message-ID", "") or number.decode()
            if (
                message_id not in re.findall(r"<[^>]+>", references)
                or sender != allowed_sender.casefold()
                or reply_id in ignored_ids
            ):
                continue
            _, full = mailbox.fetch(number, "(BODY.PEEK[])")
            message = email.message_from_bytes(full[0][1])
            return {
                "reply_id": reply_id,
                "reply": _strip_quoted(_body_text(message)),
            }
    return None


def parse_topic_reply(text: str, topics: list[Topic]) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Reply with Select: <number>, Reject all, or Feedback: <your comments>.")
    choice = re.fullmatch(r"(?:(?:select|topic)\s*:?\s*)?(\d+)", lines[0], re.I)
    selected_topic = None
    if choice:
        number = int(choice[1])
        if not 1 <= number <= len(topics):
            raise ValueError("Selected topic number is outside the emailed choices.")
        selected_topic = topics[number - 1]
        action = "select"
    elif lines[0].casefold() in {"none", "reject", "reject all"}:
        action = "reject"
    elif re.match(r"^(?:feedback|revise)\s*:", lines[0], re.I):
        action = "feedback"
    else:
        raise ValueError("Start your reply with a topic number, Reject all, or Feedback:.")
    angle = ""
    comments = []
    for line in lines if action == "feedback" else lines[1:]:
        if re.match(r"^angle\s*:", line, re.I):
            angle = line.split(":", 1)[1].strip()
        else:
            comment = re.sub(r"^(?:feedback|revise)\s*:\s*", "", line, flags=re.I)
            if comment:
                comments.append(comment)
    feedback = "\n".join(comments)
    if not topics and (action != "feedback" or not (feedback or angle)):
        raise ValueError("Reply with Feedback: and describe the topics or angle you want.")
    if action == "feedback" and not (feedback or angle):
        raise ValueError("Include feedback or a requested angle.")
    return {"action": action, "selected_topic": selected_topic, "feedback": feedback,
            "angle": angle, "raw_reply": text.strip()}


def wait_for_reply(
    message_id: str, recipient: str, topics: list[Topic], timeout_s: int = 600, poll_s: int = 10
) -> dict | None:
    deadline = time.monotonic() + timeout_s
    ignored_ids = set()
    while time.monotonic() < deadline:
        try:
            reply = fetch_reply(message_id, recipient, ignored_ids)
            if reply:
                try:
                    parse_topic_reply(reply["reply"], topics)
                except ValueError as error:
                    ignored_ids.add(reply["reply_id"])
                    logger.warning("Invalid topic review reply: %s", error)
                else:
                    return reply
        except (imaplib.IMAP4.error, OSError) as error:
            logger.warning("Email reply polling failed: %s", error)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(poll_s, remaining))
    return None


def parse_draft_reply(text: str) -> dict:
    raw = text.strip()
    if not raw:
        raise ValueError("Reply with Approve, Changes: <instructions>, Reject, or Feedback: <comments>.")
    lines = raw.splitlines()
    command = re.fullmatch(
        r"(approve|approved|reject|rejected|request changes|changes|revise|feedback)(?:\s*:\s*(.*))?",
        lines[0].strip(), re.I,
    )
    if command:
        action = {
            "approve": "approve", "approved": "approve", "reject": "reject", "rejected": "reject",
            "request changes": "request_changes", "changes": "request_changes",
            "revise": "request_changes", "feedback": "feedback",
        }[command[1].casefold()]
        feedback = "\n".join([command[2] or "", *lines[1:]]).strip()
        if action == "approve" and any(
            re.match(r"^(?:reject|rejected|request changes|changes|revise)(?:\s*:|\s*$)", line.strip(), re.I)
            for line in lines[1:]
        ):
            raise ValueError("Choose either Approve or Changes/Reject, not both.")
        if action == "approve" and feedback:
            action = "feedback"
    else:
        action, feedback = "feedback", raw
    if action in {"request_changes", "feedback"} and not feedback:
        raise ValueError("Include comments or the changes you want.")
    return {"action": action, "feedback": feedback, "raw_reply": raw}


def wait_for_draft_reply(
    message_id: str, recipient: str, timeout_s: int = 600, poll_s: int = 10,
) -> dict | None:
    deadline = time.monotonic() + timeout_s
    ignored_ids = set()
    while time.monotonic() < deadline:
        try:
            reply = fetch_reply(message_id, recipient, ignored_ids)
            if reply:
                try:
                    parse_draft_reply(reply["reply"])
                except ValueError as error:
                    ignored_ids.add(reply["reply_id"])
                    logger.warning("Invalid draft review reply: %s", error)
                else:
                    return reply
        except (imaplib.IMAP4.error, OSError) as error:
            logger.warning("Draft reply polling failed: %s", error)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(poll_s, remaining))
    return None


def send_draft_review(state: ResearchState) -> dict:
    if not state.get("draft") or state.get("writer_status") == "needs_material":
        return {"draft_review_message_id": None, "status": "no_draft_available"}
    draft = VersionedDraft.model_validate(state["draft"])
    if state.get("autonomous_active") and not review_is_current(state):
        raise ValueError("Only a passing review of the current draft and requirements can be delivered.")
    if (state.get("draft_review_message_id")
            and state.get("draft_review_version") == draft.version
            and state.get("draft_review_text") == draft.text):
        return {"status": "awaiting_draft_review"}
    user = get_database().users.find_one({"user_id": state["user_id"]}, {"_id": 0, "email": 1})
    recipient = user["email"]
    title = (state.get("selected_topic") or {}).get("title", "LinkedIn draft")
    instructions = (
        "Reply to this email with one of these on the first line:\n"
        "Approve\nChanges: Make the opening shorter and add a practical example.\n"
        "Reject: This is not the direction I want.\nFeedback: The tone is too formal.\n\n"
        "You can add more comments on the following lines. Plain-text comments count as feedback, "
        "not approval. Feedback applies to this post only. Reply with Approve alone to publish "
        "this exact version, including its title when present. Approval with comments is treated as feedback."
    )
    message_id = send_email(
        recipient, f"Review your LinkedIn draft v{draft.version} [run:{state['cycle_id']}]",
        f"<h2>{escape(title)}</h2><p>Draft version {draft.version}</p>"
        f"<div style=\"white-space: pre-wrap\">{escape(draft.text)}</div>"
        f"<hr><pre>{escape(instructions)}</pre>",
        f"{title}\nDraft version {draft.version}\n\n{draft.text}\n\n---\n{instructions}",
    )
    return {
        "draft_review_message_id": message_id, "draft_review_recipient": recipient,
        "draft_review_version": draft.version, "draft_review_text": draft.text,
        "draft_review_decision": None, "status": "awaiting_draft_review",
    }


def receive_draft_review(state: ResearchState) -> dict:
    if not state.get("draft_review_message_id"):
        return {}
    reply = interrupt({
        "type": "draft_email_review", "message_id": state["draft_review_message_id"],
        "recipient": state["draft_review_recipient"], "draft_version": state["draft_review_version"],
    })
    draft = state.get("draft") or {}
    if draft.get("version") != state["draft_review_version"] or draft.get("text") != state["draft_review_text"]:
        raise ValueError("This email reply belongs to a different draft; send the current version for review.")
    review = parse_draft_reply(reply["reply"])
    events = state.get("feedback_events", [])
    if any(event.get("stage") == "post_finalization" and event.get("run_id") == state["cycle_id"]
           and event.get("reply_id") == reply["reply_id"] for event in events):
        return {}
    event: FeedbackEvent = {
        "event_id": str(uuid4()), "user_id": state["user_id"], "run_id": state["cycle_id"],
        "stage": "post_finalization", "scope": "this_post",
        "draft_version": state["draft_review_version"], "before_text": state["draft_review_text"],
        "review_decision": review["action"], "feedback": review["feedback"],
        "raw_reply": review["raw_reply"], "message_id": state["draft_review_message_id"],
        "reply_id": reply["reply_id"], "created_at": datetime.now(timezone.utc),
        "changes": [], "processing_status": "pending",
    }
    status = {
        "approve": "draft_approved", "request_changes": "draft_changes_requested",
        "reject": "draft_rejected", "feedback": "draft_feedback_received",
    }[review["action"]]
    print("Draft feedback event:", event)
    return {"feedback_events": events + [event], "draft_review_decision": review["action"],
            "writer_feedback": review["feedback"], "status": status}


def send_topic_review(state: ResearchState) -> dict:
    if not state.get("topics"):
        return {"status": "no_topics_available", "selected_topic": None}
    user = get_database().users.find_one({"user_id": state["user_id"]})
    recipient = user["email"]
    sources = {source["id"]: source for source in state["sources"]}
    text_items = []
    html_items = []
    for number, topic in enumerate(state["topics"], 1):
        source = sources[topic["id"]]
        description = source["description"][:1000]
        text_items.append(f"{number}. {topic['title']}\n{description}\n{source['url']}")
        html_items.append(
            f"<li><strong>{escape(topic['title'])}</strong>"
            f"<p>{escape(description)}</p><p>{escape(source['url'])}</p></li>"
        )
    instructions = (
        "Reply to this email with a topic number on the first line, for example:\n"
        "Select: 2\nFeedback: Explain the practical limitations and what to improve.\n"
        "Angle: Compare the alternatives\n\n"
        "Feedback and Angle are optional and apply to this run only.\n"
        "To reject all ideas, put Reject all on the first line and explain below.\n"
        "For feedback without selecting, start with Feedback: and describe your changes."
    )
    message_id = send_email(
        recipient,
        f"Choose your LinkedIn topic [run:{state['cycle_id']}]",
        "<h2>Choose your next topic</h2><ol>" + "".join(html_items)
        + "</ol><pre>" + escape(instructions) + "</pre>",
        "Choose your next topic:\n\n" + "\n\n".join(text_items) + "\n\n" + instructions,
    )
    return {
        "topic_review_message_id": message_id,
        "topic_review_recipient": recipient,
        "status": "awaiting_topic_review",
    }


def send_topic_direction(state: ResearchState) -> dict:
    user = get_database().users.find_one({"user_id": state["user_id"]})
    reason = ("The topic retry limit was reached." if state.get("topic_retry_count", 0) > 3
              else "No suitable topic choices remain.")
    text = (
        f"{reason}\nDiscovery is paused until you provide direction.\n\n"
        "Reply with Feedback: followed by the subjects or changes you want.\n"
        "You can also add Angle: on a separate line. These instructions apply to this run only."
    )
    message_id = send_email(
        user["email"], f"Topic direction needed [run:{state['cycle_id']}]",
        f"<pre>{escape(text)}</pre>", text,
    )
    return {"topics": [], "selected_topic": None, "topic_review_message_id": message_id,
            "topic_review_recipient": user["email"], "status": "awaiting_topic_direction"}


def receive_topic_review(state: ResearchState) -> dict:
    if not state.get("topics") and state.get("status") != "awaiting_topic_direction":
        return {"status": "no_topics_available", "selected_topic": None}
    reply = interrupt({
        "type": "topic_email_review",
        "message_id": state["topic_review_message_id"],
        "recipient": state["topic_review_recipient"],
        "topics": state["topics"],
    })
    review = parse_topic_reply(reply["reply"], state["topics"])
    selected = review["selected_topic"]
    timestamp = datetime.now(timezone.utc)
    event: FeedbackEvent = {
        "event_id": str(uuid4()),
        "user_id": state["user_id"],
        "run_id": state["cycle_id"],
        "stage": "topic_selection",
        "scope": "this_post",
        "feedback": review["feedback"],
        "raw_reply": review["raw_reply"],
        "message_id": state["topic_review_message_id"],
        "reply_id": reply["reply_id"],
        "created_at": timestamp,
        "topic_decisions": [
            {
                "topic_id": topic["id"],
                "title": topic["title"],
                "decision": "selected" if selected and topic["id"] == selected["id"] else "skipped",
                "note": review["feedback"],
            }
            for topic in state["topics"]
            if review["action"] == "reject" or selected and topic["id"] == selected["id"]
        ],
        "changes": [],
        "processing_status": "pending",
    }
    requested_angle = review["angle"] or state.get("requested_angle", "")
    if requested_angle:
        event["selected_angle"] = requested_angle
    print("Feedback event:", event)
    result = {
        "selected_topic": selected,
        "feedback": "\n".join(value for value in (state.get("feedback", ""), review["feedback"]) if value),
        "requested_angle": requested_angle,
        "feedback_events": state.get("feedback_events", []) + [event],
        "decision": ("selected" if selected else "retry"
                     if review["action"] == "reject" or state.get("status") == "awaiting_topic_direction"
                     else "refine"),
        "topic_retry_count": (0 if selected or state.get("status") == "awaiting_topic_direction"
                              else state.get("topic_retry_count", 0) + 1),
        "status": "topic_selected" if selected else "topic_rejected" if review["action"] == "reject" else "topic_feedback_received",
    }
    if selected:
        result["sources"] = [
            source for source in state["sources"] if source["id"] == selected["id"]
        ]
    if review["action"] == "reject":
        result["rejected_topic_ids"] = list(dict.fromkeys(
            state.get("rejected_topic_ids", []) + [topic["id"] for topic in state["topics"]]
        ))

    print("result iss ....///////////" , result)
    return result
