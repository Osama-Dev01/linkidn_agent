import unittest
from copy import deepcopy
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph.state import ResearchState
from app.services.send_mail import (
    parse_draft_reply, receive_draft_review, send_draft_review, wait_for_draft_reply,
)


STATE = {
    "user_id": "user-1", "cycle_id": "run-1", "writer_status": "ready",
    "selected_topic": {"id": "topic-1", "title": "Context <engineering>"},
    "draft": {"text": "First paragraph.\n\nSecond <paragraph>.", "version": 2,
              "parent_version": 1, "evidence_map": []},
    "feedback_events": [],
}
SENT = {
    "draft_review_message_id": "<draft-1>", "draft_review_recipient": "user@example.org",
    "draft_review_version": 2, "draft_review_text": STATE["draft"]["text"],
}


class DraftReplyTests(unittest.TestCase):
    def test_decisions_and_comments(self):
        cases = [
            ("Approve", "approve", ""),
            ("Approve: Ready to use.", "feedback", "Ready to use."),
            ("Changes: Shorten the opening.\nUse simpler language.", "request_changes",
             "Shorten the opening.\nUse simpler language."),
            ("Reject: Wrong direction.", "reject", "Wrong direction."),
            ("Reject", "reject", ""),
            ("Feedback: Too formal.", "feedback", "Too formal."),
            ("Please make this shorter.", "feedback", "Please make this shorter."),
            ("Approve if you shorten it.", "feedback", "Approve if you shorten it."),
        ]
        for text, action, feedback in cases:
            with self.subTest(text=text):
                result = parse_draft_reply(text)
                self.assertEqual(result, {"action": action, "feedback": feedback, "raw_reply": text})

    def test_empty_and_conflicting_replies_are_not_approval(self):
        for text in (" ", "Changes:", "Feedback:", "Approve\nChanges: Shorter.", "Approve\nReject"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_draft_reply(text)

    def test_polling_filters_invalid_reply_then_collects_valid_reply(self):
        valid = {"reply_id": "<reply-2>", "reply": "Changes: Shorter."}
        with patch("app.services.send_mail.fetch_reply") as fetch, patch(
            "app.services.send_mail.time.monotonic", side_effect=[0, 1, 2, 3],
        ), patch("app.services.send_mail.time.sleep"), patch("app.services.send_mail.logger"):
            fetch.side_effect = [{"reply_id": "<reply-1>", "reply": "Changes:"}, valid]
            result = wait_for_draft_reply("<draft-1>", "user@example.org", timeout_s=10)
        self.assertEqual(result, valid)
        self.assertEqual(fetch.call_args.args[:2], ("<draft-1>", "user@example.org"))
        self.assertIn("<reply-1>", fetch.call_args.args[2])

    def test_timeout_is_not_approval(self):
        with patch("app.services.send_mail.fetch_reply") as fetch, patch(
            "app.services.send_mail.time.monotonic", side_effect=[0, 11],
        ):
            self.assertIsNone(wait_for_draft_reply("<draft-1>", "user@example.org", timeout_s=10))
            fetch.assert_not_called()


class DraftEmailTests(unittest.TestCase):
    def test_sends_only_public_draft_and_records_snapshot(self):
        state = deepcopy(STATE)
        state["claims"] = [{"text": "SECRET RESEARCH"}]
        original = deepcopy(state)
        with patch("app.services.send_mail.get_database") as database, patch(
            "app.services.send_mail.send_email", return_value="<draft-1>",
        ) as send:
            database.return_value.users.find_one.return_value = {"email": "user@example.org"}
            output = send_draft_review(state)
        recipient, subject, html, text = send.call_args.args
        self.assertEqual(recipient, "user@example.org")
        self.assertIn("v2", subject)
        self.assertIn("run:run-1", subject)
        self.assertIn(STATE["draft"]["text"], text)
        self.assertIn("&lt;paragraph&gt;", html)
        self.assertNotIn("SECRET RESEARCH", text + html)
        self.assertEqual(output["draft_review_text"], STATE["draft"]["text"])
        self.assertEqual(output["status"], "awaiting_draft_review")
        self.assertIsNone(output["draft_review_decision"])
        self.assertEqual(state, original)

    def test_does_not_send_missing_stale_or_already_sent_draft(self):
        with patch("app.services.send_mail.send_email") as send:
            self.assertEqual(send_draft_review({})["status"], "no_draft_available")
            self.assertEqual(send_draft_review({**STATE, "writer_status": "needs_material"})["status"], "no_draft_available")
            self.assertEqual(send_draft_review({**STATE, **SENT})["status"], "awaiting_draft_review")
            send.assert_not_called()

    def test_feedback_entries_are_bound_to_the_emailed_version(self):
        for reply, decision, status in (
            ("Approve", "approve", "draft_approved"),
            ("Changes: Use a concrete example.", "request_changes", "draft_changes_requested"),
            ("Reject: Wrong angle.", "reject", "draft_rejected"),
            ("Feedback: Too formal.", "feedback", "draft_feedback_received"),
        ):
            with self.subTest(reply=reply):
                state = {**deepcopy(STATE), **SENT}
                original = deepcopy(state)
                with patch("app.services.send_mail.interrupt", return_value={"reply_id": "<reply-1>", "reply": reply}), patch("builtins.print"):
                    output = receive_draft_review(state)
                event = output["feedback_events"][0]
                self.assertEqual(event["stage"], "post_finalization")
                self.assertEqual(event["scope"], "this_post")
                self.assertEqual(event["review_decision"], decision)
                self.assertEqual(event["draft_version"], 2)
                self.assertEqual(event["before_text"], SENT["draft_review_text"])
                self.assertEqual(event["raw_reply"], reply)
                self.assertEqual(event["message_id"], "<draft-1>")
                self.assertEqual(event["reply_id"], "<reply-1>")
                self.assertEqual(output["status"], status)
                self.assertEqual(state, original)
                self.assertNotIn("draft", output)

    def test_old_reply_cannot_approve_a_changed_draft(self):
        state = {**deepcopy(STATE), **SENT}
        state["draft"]["text"] = "Changed text with the same version."
        with patch("app.services.send_mail.interrupt", return_value={"reply_id": "<reply-1>", "reply": "Approve"}):
            with self.assertRaisesRegex(ValueError, "different draft"):
                receive_draft_review(state)

    def test_replayed_reply_does_not_duplicate_feedback(self):
        state = {**deepcopy(STATE), **SENT}
        with patch("app.services.send_mail.interrupt", return_value={"reply_id": "<reply-1>", "reply": "Approve"}), patch("builtins.print"):
            output = receive_draft_review(state)
            self.assertEqual(receive_draft_review({**state, **output}), {})

    def test_interrupt_resume_collects_feedback_without_resending(self):
        builder = StateGraph(ResearchState)
        builder.add_node("send", send_draft_review)
        builder.add_node("receive", receive_draft_review)
        builder.add_edge(START, "send")
        builder.add_edge("send", "receive")
        builder.add_edge("receive", END)
        graph = builder.compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "draft-email-test"}}
        with patch("app.services.send_mail.get_database") as database, patch(
            "app.services.send_mail.send_email", return_value="<draft-1>",
        ) as send, patch("builtins.print"):
            database.return_value.users.find_one.return_value = {"email": "user@example.org"}
            pending = graph.invoke(deepcopy(STATE), config=config)
            self.assertEqual(pending["__interrupt__"][0].value["type"], "draft_email_review")
            completed = graph.invoke(Command(resume={"reply_id": "<reply-1>", "reply": "Changes: Shorter."}), config=config)
            send.assert_called_once()
        self.assertEqual(completed["status"], "draft_changes_requested")
        self.assertEqual(completed["draft"], STATE["draft"])
        self.assertEqual(len(completed["feedback_events"]), 1)
        self.assertFalse(completed.get("__interrupt__"))


if __name__ == "__main__":
    unittest.main()
