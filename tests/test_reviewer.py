import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from app.autonomous.reviewer import review_post
from app.autonomous.reviewer_schema import QualityReview
from app.autonomous.writer import _writing_samples, write_post
from app.autonomous.writer_schema import WriterResult


TEXT = "The trial involved 40 participants."
CLAIM = {
    "id": "claim-1", "text": TEXT, "status": "supported", "qualifications": [],
    "evidence": [{"source_id": "source-1", "passage": TEXT, "kind": "cited_finding"}],
    "reason": "The finding specifies the trial size.",
}
DRAFT = {
    "text": TEXT, "version": 1, "parent_version": None,
    "evidence_map": [{"draft_span": TEXT, "claim_ids": ["claim-1"], "personal_material_ids": []}],
}
SAMPLE = {
    "id": "sample-1", "text": "I start with a small test. Then I check what changed.",
    "authorship": "Written by me", "sounds_like_me": "Yes", "content_type": "LinkedIn post",
}
STATE = {
    "user_id": "user-1", "draft": DRAFT, "writer_status": "ready",
    "selected_topic": {"id": "source-1", "title": "Trial findings"},
    "brief": {"central_question": "What did the trial show?"},
    "claims": [CLAIM],
    "research_sources": [{"id": "source-1", "title": "Trial", "cited_findings": [TEXT],
                          "body": "Do not send a full article."}],
    "writer_context": {"user_id": "user-1", "draft_version": 1,
                       "writing_preferences": {"voice_instructions": "Short direct sentences."},
                       "writing_samples": [SAMPLE], "audience": {"target_audience": ["Teachers"]}},
}
PASS = {"draft_version": 1, "verdict": "pass", "findings": [], "limitations": []}


class ReviewerTests(unittest.TestCase):
    def run_review(self, state=None, result=None, profile=None):
        with patch("app.autonomous.reviewer._get_chain") as chain, patch(
            "app.autonomous.reviewer.get_database",
        ) as database, patch("builtins.print"):
            database.return_value.profiles.find_one.return_value = profile or {}
            chain.return_value.invoke.return_value = QualityReview.model_validate(result or PASS)
            output = review_post(deepcopy(STATE) if state is None else state)
        inputs = (json.loads(chain.return_value.invoke.call_args.args[0]["review_input"])
                  if chain.return_value.invoke.called else None)
        return output, inputs, chain, database

    def test_review_receives_evidence_and_same_voice_context_without_editing(self):
        state = deepcopy(STATE)
        original = deepcopy(state)
        output, inputs, chain, database = self.run_review(state)
        self.assertEqual(output["quality_review"]["verdict"], "pass")
        self.assertEqual(inputs["writing_samples"], state["writer_context"]["writing_samples"])
        self.assertEqual(inputs["writing_preferences"], state["writer_context"]["writing_preferences"])
        self.assertEqual(inputs["claims"][0]["evidence"][0]["passage"], TEXT)
        self.assertEqual(inputs["supporting_sources"][0]["cited_findings"], [TEXT])
        self.assertNotIn("body", inputs["supporting_sources"][0])
        self.assertEqual(state, original)
        self.assertNotIn("draft", output)
        chain.return_value.invoke.assert_called_once()
        database.assert_not_called()

    def test_writer_and_reviewer_use_identical_selected_samples(self):
        samples = [
            {**SAMPLE, "id": "article", "content_type": "Article"},
            {**SAMPLE, "id": "someone-else", "authorship": "Written by someone else"},
            {**SAMPLE, "id": "not-me", "sounds_like_me": "No"},
            {**SAMPLE, "id": "unknown", "authorship": "Mixed / unknown"},
            SAMPLE,
            {**SAMPLE, "id": "edited", "authorship": "AI-assisted and edited by me"},
            {**SAMPLE, "id": "third"},
        ]
        state = deepcopy(STATE)
        state.pop("draft")
        with patch("app.autonomous.writer.get_database") as database, patch(
            "app.autonomous.writer._get_chain",
        ) as chain, patch("builtins.print"):
            database.return_value.profiles.find_one.return_value = {
                "writing_samples": {"items": samples}, "preferences": {"tone": ["Curious"]},
            }
            chain.return_value.invoke.return_value = WriterResult(
                text=TEXT, evidence_map=DRAFT["evidence_map"], work_request=None,
            )
            generated = write_post(state)
        writer_input = json.loads(chain.return_value.invoke.call_args.args[0]["writer_input"])
        _, reviewer_input, _, _ = self.run_review({**state, **generated})
        self.assertEqual([item["id"] for item in writer_input["writing_samples"]], ["sample-1", "edited", "third"])
        self.assertEqual(writer_input["writing_samples"], reviewer_input["writing_samples"])
        self.assertEqual(writer_input["writing_preferences"], reviewer_input["writing_preferences"])
        self.assertEqual(writer_input["supporting_sources"], reviewer_input["supporting_sources"])
        self.assertEqual(
            [{key: value for key, value in claim.items() if key != "source_ids"}
             for claim in writer_input["usable_claims"]], reviewer_input["claims"],
        )

    def test_partly_samples_are_included_with_their_labels_and_notes(self):
        samples = [
            {**SAMPLE, "id": "partly-edited", "sounds_like_me": "Partly",
             "authorship": "AI-assisted and edited by me", "notes": "Prefer the direct opening."},
            SAMPLE,
            {**SAMPLE, "id": "partly-written", "sounds_like_me": "Partly"},
        ]
        selected = _writing_samples({"writing_samples": {"items": samples}})
        self.assertEqual([item["id"] for item in selected], ["sample-1", "partly-edited", "partly-written"])
        self.assertEqual(selected[1]["sounds_like_me"], "Partly")
        self.assertEqual(selected[1]["notes"], "Prefer the direct opening.")

    def test_legacy_profile_summary_is_not_sent_and_history_notice_is_not_added(self):
        state = deepcopy(STATE)
        state["writer_context"]["profile_summary"] = "LEGACY PERSONAL SUMMARY"
        state["summary"] = "CURRENT PERSONAL SUMMARY"
        output, inputs, _, _ = self.run_review(state)
        self.assertNotIn("profile_summary", inputs)
        self.assertNotIn("PERSONAL SUMMARY", json.dumps(inputs))
        self.assertEqual(output["quality_review"]["limitations"], [])

    def test_deterministic_failures_cannot_be_waived_by_model(self):
        state = deepcopy(STATE)
        state["draft"]["text"] += " Very unique. 👩🏽‍💻 #trial #research"
        state["writer_context"]["writing_preferences"] = {
            "word_range": "1-3", "hashtag_max": 1, "emojis": "None", "avoided_phrases": ["Very unique"],
        }
        output, inputs, _, _ = self.run_review(state)
        review = output["quality_review"]
        self.assertEqual(review["verdict"], "revise")
        self.assertEqual(len(review["findings"]), 4)
        self.assertEqual(review["deterministic_checks"]["emoji_count"], 1)
        self.assertEqual(review["deterministic_checks"]["hashtag_count"], 2)
        self.assertEqual(len(inputs["deterministic_checks"]["findings"]), 4)
        self.assertEqual(len({finding["id"] for finding in review["findings"]}), 4)

    def test_soft_preferences_do_not_create_numeric_limits(self):
        state = deepcopy(STATE)
        state["writer_context"]["writing_preferences"] = {"emojis": "Occasional", "hashtags": "Automatic"}
        state["draft"]["text"] += " 👋 #trial"
        output, _, _, _ = self.run_review(state)
        self.assertEqual(output["quality_review"]["verdict"], "pass")

    def test_unmapped_assertions_can_be_compared_with_available_claims(self):
        state = deepcopy(STATE)
        state["draft"]["evidence_map"] = []
        _, inputs, _, _ = self.run_review(state)
        self.assertEqual(inputs["claims"], [CLAIM])
        self.assertEqual(inputs["supporting_sources"][0]["cited_findings"], [TEXT])

    def test_missing_references_and_fabricated_passages_are_flagged(self):
        for change in ("claim", "source", "passage", "span"):
            state = deepcopy(STATE)
            if change == "claim":
                state["claims"] = []
            elif change == "source":
                state["research_sources"] = []
            elif change == "passage":
                state["claims"][0]["evidence"][0]["passage"] = "Invented result"
            else:
                state["draft"]["evidence_map"][0]["draft_span"] = "Absent span"
            with self.subTest(change=change):
                output, _, _, _ = self.run_review(state)
                self.assertEqual(output["quality_review"]["verdict"], "revise")
                self.assertTrue(any(item["severity"] == "blocking" for item in output["quality_review"]["findings"]))

    def test_personal_permissions_are_rechecked_and_private_details_excluded(self):
        state = deepcopy(STATE)
        state["draft"]["evidence_map"][0]["personal_material_ids"] = ["experience-1"]
        experience = {"id": "experience-1", "usage_permission": "May use in drafts",
                      "permitted_details": ["Role"], "personal_role": "Teacher",
                      "outcome": "PRIVATE OUTCOME", "anonymisation": "Do not name my school."}
        profile = {"experiences": {"items": [experience]}}
        _, inputs, _, _ = self.run_review(state, profile=profile)
        self.assertNotIn("PRIVATE OUTCOME", json.dumps(inputs))
        self.assertEqual(inputs["personal_material"][0]["anonymisation"], "Do not name my school.")
        experience["usage_permission"] = "Private context only"
        output, inputs, _, _ = self.run_review(state, profile=profile)
        self.assertEqual(inputs["personal_material"], [])
        self.assertEqual(output["quality_review"]["findings"][0]["kind"], "personal_material")

    def test_missing_or_mismatched_context_holds_without_model(self):
        for context in ({}, {**STATE["writer_context"], "draft_version": 2},
                        {**STATE["writer_context"], "user_id": "someone-else"}):
            with self.subTest(context=context):
                output, inputs, chain, _ = self.run_review({**deepcopy(STATE), "writer_context": context})
                self.assertEqual(output["quality_review"]["verdict"], "hold")
                self.assertIsNone(inputs)
                chain.assert_not_called()

    def test_invalid_draft_holds_without_model(self):
        state = deepcopy(STATE)
        del state["draft"]["version"]
        output, _, chain, _ = self.run_review(state)
        self.assertEqual(output["quality_review"]["verdict"], "hold")
        chain.assert_not_called()

    def test_no_draft_or_waiting_writer_does_not_review_stale_draft(self):
        for state in ({}, {**deepcopy(STATE), "writer_status": "needs_material"}):
            output, _, chain, database = self.run_review(state)
            self.assertIsNone(output["quality_review"])
            chain.assert_not_called()
            database.assert_not_called()

    def test_mismatched_version_or_invented_review_span_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "different draft version"):
            self.run_review(result={**PASS, "draft_version": 2})
        finding = {"kind": "voice", "severity": "major", "suggested_owner": "writer",
                   "draft_span": "Invented span", "evidence": "Prefers short sentences.",
                   "required_change": "Split the sentence."}
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.run_review(result={**PASS, "verdict": "revise", "findings": [finding]})

    def test_missing_samples_is_a_limitation_not_a_voice_failure(self):
        state = deepcopy(STATE)
        state["writer_context"]["writing_samples"] = []
        output, _, _, _ = self.run_review(state)
        self.assertEqual(output["quality_review"]["verdict"], "pass")
        self.assertIn("No eligible writing samples", " ".join(output["quality_review"]["limitations"]))

    def test_schema_requires_concrete_findings_and_rejects_false_pass(self):
        schema = to_strict_json_schema(QualityReview)
        self.assertFalse(schema["additionalProperties"])
        finding = {"kind": "voice", "severity": "major", "suggested_owner": "writer",
                   "draft_span": TEXT, "evidence": "Prefers short sentences.",
                   "required_change": "Split the sentence."}
        with self.assertRaises(ValidationError):
            QualityReview.model_validate({**PASS, "findings": [finding]})
        with self.assertRaisesRegex(ValueError, "concrete finding"):
            self.run_review(result={**PASS, "verdict": "revise"})


if __name__ == "__main__":
    unittest.main()
