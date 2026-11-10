from html import escape

from app.db.client import get_database
from app.services.send_mail import send_email


def request_draft_clarification(state):
    draft = state.get("draft") or {}
    version = draft.get("version")
    user = get_database().users.find_one({"user_id": state["user_id"]}, {"_id": 0, "email": 1})
    text = (f"{state['supervisor_question']}\n\nReply with Feedback: followed by your clarification.\n"
            "This question concerns your requested edits; it is not a publication approval request.")
    message_id = send_email(user["email"], f"Clarify draft {version or 'requirements'} [run:{state['cycle_id']}]",
                            f"<pre>{escape(text)}</pre>", text)
    return {"draft_review_message_id": message_id, "draft_review_recipient": user["email"],
            "draft_review_version": version, "draft_review_text": draft.get("text"),
            "draft_review_decision": None, "awaiting_draft_clarification": True,
            "status": "awaiting_draft_clarification"}
