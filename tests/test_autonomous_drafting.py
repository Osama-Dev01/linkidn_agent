import json
import unittest
from contextlib import ExitStack
from copy import deepcopy
from importlib import import_module
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from app.autonomous.feedback_processor import FeedbackPlan, process_feedback
from app.autonomous.reviewer_schema import QualityReview
from app.autonomous.supervisor import review_is_current
from app.autonomous.writer_schema import WriterResult
from app.services.linkedin import publish_approved_post
from app.services.send_mail import parse_draft_reply, send_draft_review
from tests.test_reviewer import STATE, TEXT


EMPTY_OVERRIDES = {"word_range": None, "hashtag_max": None, "hashtags": None, "emojis": None}


def requirement(instruction="Simplify the language.", kind="voice", supersedes=None):
    return {"instruction": instruction, "kind": kind,
            "acceptance_condition": instruction, "supersedes": supersedes or []}


def plan(items=None, question=None, overrides=None):
    return FeedbackPlan(requirements=items or [], clarification_question=question,
                        preference_overrides={**EMPTY_OVERRIDES, **(overrides or {})})


class AutonomousDraftingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("builtins.print"))
        self.stack.enter_context(patch("app.db.client.get_checkpointer", return_value=InMemorySaver()))
        self.stack.enter_context(patch("app.services.preference_learning.get_database"))
        learning = self.stack.enter_context(patch("app.services.preference_learning._get_chain"))
        from app.services.preference_learning import PreferenceUpdates
        learning.return_value.invoke.return_value = PreferenceUpdates(updates=[])
        self.learning = learning.return_value.invoke
        self.graph = import_module("app.graph.builder").builder.compile(checkpointer=InMemorySaver())
        self.config = {"configurable": {"thread_id": self.id()}, "recursion_limit": 100}
        self.initial = {**deepcopy(STATE), "cycle_id": "run-1", "feedback_events": []}
        for key in ("draft", "writer_status", "writer_context"):
            self.initial.pop(key)
        self.writer_inputs = []
        self.review_inputs = []
        self.feedback_inputs = []
        self.plans = []
        self.verdicts = []
        self.same_text = False
        self.work_request = False
        self.profile = {}
        writer = self.stack.enter_context(patch("app.autonomous.writer._get_chain"))
        writer.return_value.invoke.side_effect = self.write
        reviewer = self.stack.enter_context(patch("app.autonomous.reviewer._get_chain"))
        reviewer.return_value.invoke.side_effect = self.review
        processor = self.stack.enter_context(patch("app.autonomous.feedback_processor._get_chain"))
        processor.return_value.invoke.side_effect = self.process
        database = self.stack.enter_context(patch("app.autonomous.writer.get_database")).return_value
        database.profiles.find_one.side_effect = lambda *args: deepcopy(self.profile)
        for target in ("app.services.send_mail.get_database", "app.autonomous.draft_clarification.get_database"):
            database = self.stack.enter_context(patch(target)).return_value
            database.users.find_one.return_value = {"email": "user@example.org"}
        self.send = self.stack.enter_context(patch("app.services.send_mail.send_email"))
        self.send.side_effect = lambda *args: f"<draft-{self.send.call_count}>"
        self.clarify = self.stack.enter_context(patch("app.autonomous.draft_clarification.send_email", return_value="<clarify>"))
        self.publish = self.stack.enter_context(patch("app.services.linkedin.publish_post", return_value="post-1"))
        self.stack.enter_context(patch("app.services.linkedin.get_database"))

    def write(self, arguments):
        inputs = json.loads(arguments["writer_input"])
        self.writer_inputs.append(inputs)
        if self.work_request:
            return WriterResult(text=None, evidence_map=[], work_request={
                "question": "Can you supply an example?", "why_needed": "No example supplied.",
            })
        index = 1 if self.same_text else len(self.writer_inputs)
        text = f"Trial findings\n\n{TEXT}\n\nConsider the scope. Revision {index}."
        if self.profile.get("preferences", {}).get("word_range"):
            count = 110 if inputs["writing_preferences"].get("word_range") == "100-130" else 260
            text = "Trial findings\n\n" + "Clear " * count + TEXT
        return WriterResult(text=text, work_request=None, evidence_map=[{
            "draft_span": TEXT, "claim_ids": ["claim-1"], "personal_material_ids": [],
        }])

    def review(self, arguments):
        inputs = json.loads(arguments["review_input"])
        self.review_inputs.append(inputs)
        verdict = self.verdicts.pop(0) if self.verdicts else "pass"
        findings = [] if verdict == "pass" else [{
            "kind": "readability", "severity": "major", "suggested_owner": "writer",
            "draft_span": None, "evidence": "The explanation is too abstract.",
            "required_change": "Explain the practical implication clearly.",
        }]
        return QualityReview(draft_version=inputs["draft_version"], verdict=verdict,
                             findings=findings, limitations=[], requirement_results=[
                                 {"requirement_id": item["id"], "status": "satisfied",
                                  "evidence": "The draft follows the instruction."}
                                 for item in inputs["draft_requirements"]
                             ])

    def process(self, arguments):
        self.feedback_inputs.append(json.loads(arguments["feedback_input"]))
        return self.plans.pop(0) if self.plans else plan([requirement()])

    def start(self):
        self.graph.update_state(self.config, self.initial, as_node="researcher")
        return self.graph.invoke(None, self.config)

    def reply(self, text):
        return self.graph.invoke(Command(resume={"reply_id": f"<reply-{self.send.call_count}-{self.clarify.call_count}>",
                                                "reply": text}), self.config)

    def test_review_failure_rewrites_before_delivery_and_approval_publishes_exact_text(self):
        self.verdicts = ["revise", "pass"]
        result = self.start()
        self.assertTrue(result.get("__interrupt__"))
        self.assertEqual(result["draft"]["version"], 2)
        self.assertEqual(len(self.writer_inputs), 2)
        self.assertEqual(len(self.review_inputs), 2)
        self.assertIn("Explain the practical implication", self.writer_inputs[1]["revision_instructions"])
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(len(result["draft_history"]), 2)
        self.assertEqual(result["open_draft_issues"], [])
        self.assertEqual(len(result["resolved_draft_issue_ids"]), 1)
        self.assertTrue(review_is_current(result))
        self.learning.assert_not_called()
        approved = self.reply("Approve")
        self.assertEqual(approved["status"], "published")
        self.publish.assert_called_once_with(result["draft"]["text"])
        self.assertEqual(self.publish.call_args.args[0].count("Trial findings"), 1)
        self.learning.assert_called_once()

    def test_failed_publication_does_not_learn_preferences(self):
        self.start()
        self.publish.side_effect = RuntimeError("Publication failed")
        with self.assertRaisesRegex(RuntimeError, "Publication failed"):
            self.reply("Approve")
        self.learning.assert_not_called()

    def test_user_feedback_is_processed_then_rewritten_and_reviewed(self):
        first = self.start()
        result = self.reply("Changes: Simplify the language.")
        self.assertTrue(result.get("__interrupt__"))
        self.assertEqual(result["draft"]["version"], 2)
        self.assertEqual(result["draft"]["parent_version"], 1)
        self.assertEqual(result["draft_requirements"]["version"], 2)
        requirements = result["draft_requirements"]["items"]
        self.assertEqual(self.writer_inputs[-1]["draft_requirements"], requirements)
        self.assertEqual(self.review_inputs[-1]["draft_requirements"], requirements)
        self.assertEqual(self.writer_inputs[-1]["previous_draft"], first["draft"]["text"])
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual(self.publish.call_count, 0)
        self.assertIsNone(result["draft_review_decision"])

    def test_current_length_overrides_saved_range_in_writer_and_reviewer(self):
        self.profile = {"preferences": {"word_range": "250-300"}}
        self.plans = [plan([requirement("Use 100-130 words.", "length")], overrides={"word_range": "100-130"})]
        self.start()
        result = self.reply("Changes: Use 100-130 words.")
        self.assertTrue(review_is_current(result))
        self.assertEqual(self.writer_inputs[-1]["writing_preferences"]["word_range"], "100-130")
        self.assertEqual(self.review_inputs[-1]["writing_preferences"]["word_range"], "100-130")
        self.assertEqual(result["quality_review"]["deterministic_checks"]["word_count"], 117)

    def test_three_revisions_stop_without_delivering_failed_draft(self):
        self.verdicts = ["revise"] * 4
        result = self.start()
        self.assertEqual(result["status"], "draft_revision_limit_reached")
        self.assertEqual(result["revision_count"], 3)
        self.assertEqual(len(self.writer_inputs), 4)
        self.assertEqual(self.send.call_count, 0)
        self.assertEqual(self.clarify.call_count, 0)
        self.assertEqual(self.publish.call_count, 0)

    def test_identical_failed_revision_stops_as_stalled(self):
        self.same_text = True
        self.verdicts = ["revise", "revise"]
        result = self.start()
        self.assertEqual(result["status"], "draft_revision_stalled")
        self.assertEqual(len(self.writer_inputs), 2)
        self.assertEqual(self.send.call_count, 0)

    def test_missing_material_does_not_ask_user_or_start_research(self):
        self.work_request = True
        result = self.start()
        self.assertEqual(result["status"], "draft_revision_limit_reached")
        self.assertEqual(len(self.writer_inputs), 4)
        self.assertEqual(self.send.call_count, 0)
        self.assertEqual(self.clarify.call_count, 0)
        self.assertIn("Do not request material", self.writer_inputs[-1]["revision_instructions"])

    def test_no_supported_claims_stops_without_fabricating_a_draft(self):
        self.initial["claims"] = []
        result = self.start()
        self.assertEqual(result["status"], "draft_revision_limit_reached")
        self.assertEqual(len(self.writer_inputs), 0)
        self.assertNotIn("draft", result)
        self.assertEqual(self.clarify.call_count, 0)

    def test_invalid_support_and_unavailable_personal_material_are_omitted(self):
        invalid = deepcopy(self.initial["claims"][0])
        invalid["id"] = "invalid-claim"
        invalid["evidence"][0]["source_id"] = "missing-source"
        self.initial["claims"].append(invalid)
        self.initial["writer_personal_material_ids"] = ["private-record"]
        result = self.start()
        self.assertTrue(review_is_current(result))
        self.assertEqual([claim["id"] for claim in self.writer_inputs[0]["usable_claims"]], ["claim-1"])
        self.assertEqual(self.writer_inputs[0]["personal_material"], [])
        self.assertEqual(self.clarify.call_count, 0)

    def test_ambiguous_feedback_is_clarified_and_original_request_is_preserved(self):
        self.plans = [plan(question="Which part should stay unchanged?"), plan([requirement("Keep the opening.", "preserve")])]
        self.start()
        pending = self.reply("Feedback: Keep that part.")
        self.assertEqual(pending["status"], "awaiting_draft_clarification")
        self.assertEqual(len(self.writer_inputs), 1)
        result = self.reply("Feedback: The opening.")
        self.assertEqual(result["draft"]["version"], 2)
        self.assertIn("Keep that part.", self.feedback_inputs[-1]["feedback"])
        self.assertIn("The opening.", self.feedback_inputs[-1]["feedback"])
        self.assertEqual(result["pending_draft_feedback"], "")

    def test_initial_ambiguity_can_be_clarified_before_first_draft(self):
        self.initial["instructions"] = "Keep that part."
        self.plans = [plan(question="Which passage should be preserved?"), plan([requirement()])]
        result = self.start()
        self.assertEqual(result["status"], "awaiting_draft_clarification")
        self.assertNotIn("draft", result)
        result = self.reply("Feedback: Use simpler wording throughout.")
        self.assertTrue(result.get("__interrupt__"))
        self.assertEqual(result["draft"]["version"], 1)

    def test_rejection_ends_without_another_draft_or_publication(self):
        self.start()
        result = self.reply("Reject: Wrong direction.")
        self.assertEqual(result["status"], "draft_rejected")
        self.assertEqual(len(self.writer_inputs), 1)
        self.assertEqual(self.publish.call_count, 0)

    def test_delivery_and_publication_reject_stale_or_failed_reviews(self):
        state = self.start()
        for change in ("text", "requirements", "verdict", "user", "context", "version"):
            modified = deepcopy(state)
            modified["draft_review_decision"] = "approve"
            if change == "text":
                modified["draft"]["text"] += " Changed."
            elif change == "requirements":
                modified["draft_requirements"]["version"] += 1
            elif change == "verdict":
                modified["quality_review"]["verdict"] = "hold"
            elif change == "user":
                modified["user_id"] = "other-user"
            elif change == "context":
                modified["writer_context"]["draft_version"] += 1
            else:
                modified["draft_review_version"] += 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                publish_approved_post(modified)
            if change != "version":
                with self.subTest(delivery=change), self.assertRaises(ValueError):
                    send_draft_review(modified)
        self.assertEqual(self.publish.call_count, 0)

    def test_reviewer_cannot_skip_active_requirements(self):
        self.initial["instructions"] = "Simplify the language."
        with patch("app.autonomous.reviewer._get_chain") as reviewer:
            reviewer.return_value.invoke.return_value = QualityReview(
                draft_version=1, verdict="pass", findings=[], limitations=[], requirement_results=[],
            )
            with self.assertRaisesRegex(ValueError, "every active requirement"):
                self.start()
        self.assertEqual(self.send.call_count, 0)

    def test_hold_returns_to_writer_without_requesting_supporting_material(self):
        self.verdicts = ["hold", "pass"]
        result = self.start()
        self.assertTrue(review_is_current(result))
        self.assertEqual(len(self.writer_inputs), 2)
        self.assertEqual(self.clarify.call_count, 0)
        self.assertEqual(self.send.call_count, 1)

    def test_new_user_feedback_gets_its_own_bounded_revision_round(self):
        self.verdicts = ["revise"] * 3 + ["pass"]
        first = self.start()
        self.assertEqual(first["revision_count"], 3)
        self.verdicts = ["revise"] * 3 + ["pass"]
        result = self.reply("Changes: Simplify the explanation.")
        self.assertTrue(review_is_current(result))
        self.assertEqual(result["revision_count"], 3)
        self.assertEqual(result["draft"]["version"], 8)
        self.assertEqual(self.send.call_count, 2)

    def test_repeated_issue_keeps_its_id_until_resolved(self):
        self.verdicts = ["revise", "revise", "pass"]
        result = self.start()
        self.assertEqual(self.writer_inputs[1]["assigned_issues"], self.writer_inputs[2]["assigned_issues"])
        self.assertEqual(result["resolved_draft_issue_ids"], self.writer_inputs[1]["assigned_issues"])
        self.assertEqual(result["open_draft_issues"], [])

    def test_minor_observation_does_not_start_an_unnecessary_revision(self):
        original = self.review

        def minor_review(arguments):
            review = original(arguments).model_dump()
            review["findings"] = [{"kind": "readability", "severity": "minor", "suggested_owner": "writer",
                                "draft_span": None, "evidence": "A harmless wording alternative exists.",
                                "required_change": "Optionally simplify the final phrase."}]
            return QualityReview.model_validate(review)

        with patch("app.autonomous.reviewer._get_chain") as reviewer:
            reviewer.return_value.invoke.side_effect = minor_review
            result = self.start()
        self.assertTrue(review_is_current(result))
        self.assertEqual(len(self.writer_inputs), 1)

    def test_reviewer_wrong_version_blocks_delivery(self):
        with patch("app.autonomous.reviewer._get_chain") as reviewer:
            reviewer.return_value.invoke.return_value = QualityReview(
                draft_version=99, verdict="pass", findings=[], limitations=[],
            )
            with self.assertRaisesRegex(ValueError, "different draft version"):
                self.start()
        self.assertEqual(self.send.call_count, 0)
        self.assertEqual(self.publish.call_count, 0)

    def test_writer_cannot_reference_invented_claim_ids(self):
        with patch("app.autonomous.writer._get_chain") as writer:
            writer.return_value.invoke.return_value = WriterResult(
                text=TEXT, work_request=None, evidence_map=[{
                    "draft_span": TEXT, "claim_ids": ["invented"], "personal_material_ids": [],
                }],
            )
            with self.assertRaisesRegex(ValueError, "unavailable material"):
                self.start()
        self.assertEqual(self.send.call_count, 0)

    def test_duplicate_requirement_assessments_cannot_pass(self):
        self.initial["instructions"] = "Simplify the language."

        def duplicated_review(arguments):
            inputs = json.loads(arguments["review_input"])
            item = {"requirement_id": inputs["draft_requirements"][0]["id"],
                    "status": "satisfied", "evidence": "The draft is clear."}
            return QualityReview(draft_version=inputs["draft_version"], verdict="pass",
                                 findings=[], limitations=[], requirement_results=[item, item])

        with patch("app.autonomous.reviewer._get_chain") as reviewer:
            reviewer.return_value.invoke.side_effect = duplicated_review
            with self.assertRaisesRegex(ValueError, "exactly once"):
                self.start()
        self.assertEqual(self.send.call_count, 0)

    def test_model_failure_does_not_deliver_or_publish_a_draft(self):
        with patch("app.autonomous.writer._get_chain") as writer:
            writer.return_value.invoke.side_effect = TimeoutError("Simulated model timeout")
            with self.assertRaises(TimeoutError):
                self.start()
        self.assertEqual(self.send.call_count, 0)
        self.assertEqual(self.publish.call_count, 0)

    def test_approval_with_changes_triggers_revision_instead_of_publication(self):
        self.start()
        result = self.reply("Approve: Simplify the language before publishing.")
        self.assertTrue(result.get("__interrupt__"))
        self.assertEqual(result["draft"]["version"], 2)
        self.assertEqual(self.publish.call_count, 0)


class FeedbackValidationTests(unittest.TestCase):
    def state(self):
        return {"user_id": "user-1", "cycle_id": "run-1", "feedback": "Shorter, please.",
                "draft_requirements": {"version": 1, "user_id": "user-1", "run_id": "run-1",
                                       "items": [{"id": "old-length", "kind": "length"}],
                                       "preference_overrides": {"word_range": "250-300"}}}

    def test_new_length_replaces_old_requirement_without_inventing_word_count(self):
        with patch("app.autonomous.feedback_processor._get_chain") as chain:
            chain.return_value.invoke.return_value = plan([requirement("Shorten the draft.", "length")])
            result = process_feedback(self.state())
        requirements = result["draft_requirements"]
        self.assertEqual(len(requirements["items"]), 1)
        self.assertEqual(requirements["preference_overrides"]["word_range"], "")

    def test_unknown_superseded_requirement_and_stale_feedback_are_rejected(self):
        with patch("app.autonomous.feedback_processor._get_chain") as chain:
            chain.return_value.invoke.return_value = plan([requirement(supersedes=["invented"])])
            with self.assertRaisesRegex(ValueError, "unknown requirement"):
                process_feedback(self.state())
        state = self.state()
        state.update({"draft": {"version": 2}, "feedback_events": [{
            "event_id": "event-1", "stage": "post_finalization", "user_id": "user-1",
            "run_id": "run-1", "draft_version": 1, "feedback": "Shorter.",
        }]})
        with self.assertRaisesRegex(ValueError, "different draft"):
            process_feedback(state)

    def test_false_pass_and_invalid_numeric_targets_are_rejected(self):
        with self.assertRaises(ValidationError):
            QualityReview(draft_version=1, verdict="pass", findings=[], limitations=[], requirement_results=[
                {"requirement_id": "r1", "status": "unmet", "evidence": "Still too long."},
            ])
        for target in ("200-100", "0-100", "shorter"):
            with self.subTest(target=target), self.assertRaises(ValidationError):
                plan(overrides={"word_range": target})

    def test_conditional_approval_is_feedback(self):
        self.assertEqual(parse_draft_reply("Approve: Shorten it before posting.")["action"], "feedback")
        self.assertEqual(parse_draft_reply("Approve")["action"], "approve")

    def test_local_length_change_preserves_total_word_range_and_opening_constraint(self):
        state = self.state()
        state["draft_requirements"]["items"] = [
            {"id": "total-length", "kind": "length", "scope": "post",
             "instruction": "Use 250-300 words.", "acceptance_condition": "The post has 250-300 words."},
            {"id": "opening-length", "kind": "length", "scope": "opening",
             "instruction": "Keep the opening under 20 words.", "acceptance_condition": "Opening is under 20 words."},
        ]
        result = plan([requirement("Shorten the closing.", "length")])
        result.requirements[0] = result.requirements[0].model_copy(update={"scope": "closing"})
        with patch("app.autonomous.feedback_processor._get_chain") as chain:
            chain.return_value.invoke.return_value = result
            output = process_feedback(state)
        active = {item["id"] for item in output["draft_requirements"]["items"]}
        self.assertTrue({"total-length", "opening-length"}.issubset(active))
        self.assertEqual(output["draft_requirements"]["preference_overrides"]["word_range"], "250-300")

    def test_allowing_hashtags_clears_superseded_zero_limit(self):
        state = self.state()
        state["draft_requirements"]["items"] = [
            {"id": "no-hashtags", "kind": "formatting", "instruction": "No hashtags.",
             "acceptance_condition": "The post has no hashtags."},
        ]
        state["draft_requirements"]["preference_overrides"] = {"hashtags": "None", "hashtag_max": 0}
        with patch("app.autonomous.feedback_processor._get_chain") as chain:
            chain.return_value.invoke.return_value = plan(
                [requirement("Choose hashtags automatically.", "formatting", ["no-hashtags"])],
                overrides={"hashtags": "Automatic"},
            )
            output = process_feedback(state)
        overrides = output["draft_requirements"]["preference_overrides"]
        self.assertEqual(overrides["hashtags"], "Automatic")
        self.assertIsNone(overrides.get("hashtag_max"))


if __name__ == "__main__":
    unittest.main()
