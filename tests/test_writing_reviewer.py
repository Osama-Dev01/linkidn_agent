import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from pydantic import ValidationError

from app.autonomous.writing_reviewer import WritingReview, review_writing
from tests.test_reviewer import PASS, STATE, TEXT


class WritingReviewerTests(unittest.TestCase):
    def run_review(self, state=None, result=None, profile=None):
        with patch("app.autonomous.writing_reviewer._get_chain") as chain, patch(
            "app.autonomous.writing_reviewer.get_database",
        ) as database, patch("builtins.print"):
            database.return_value.profiles.find_one.return_value = profile or {}
            chain.return_value.invoke.return_value = WritingReview.model_validate(result or PASS)
            output = review_writing(deepcopy(STATE) if state is None else state)
        inputs = (json.loads(chain.return_value.invoke.call_args.args[0]["review_input"])
                  if chain.return_value.invoke.called else None)
        return output, inputs, chain, database

    def test_input_excludes_all_research_and_preserves_writing_context(self):
        state = deepcopy(STATE)
        state["claims"][0]["text"] = "SECRET RESEARCH CLAIM"
        state["research_sources"][0]["cited_findings"] = ["SECRET SUPPORTING PASSAGE"]
        state["gaps"] = [{"question": "SECRET RESEARCH GAP"}]
        state["brief"]["research_questions"] = ["SECRET RESEARCH QUESTION"]
        state["writer_context"]["profile_summary"] = "SECRET PERSONAL SUMMARY"
        state["writer_context"]["current_instructions"] = "Explain simply."
        original = deepcopy(state)
        output, inputs, chain, database = self.run_review(state)
        self.assertNotIn("SECRET", json.dumps(inputs))
        for key in ("claims", "research_gaps", "supporting_sources", "evidence_map", "profile_summary"):
            self.assertNotIn(key, inputs)
        self.assertEqual(inputs["draft_text"], TEXT)
        self.assertEqual(inputs["writing_samples"], state["writer_context"]["writing_samples"])
        self.assertEqual(inputs["writing_preferences"], state["writer_context"]["writing_preferences"])
        self.assertEqual(inputs["current_instructions"], "Explain simply.")
        review = output["writing_review"]
        self.assertEqual(review["verdict"], "pass")
        self.assertEqual(review["scope"], "writing_quality_only")
        self.assertNotIn("factual_verification", review)
        self.assertIsNone(output["quality_review"])
        self.assertEqual(state, original)
        chain.return_value.invoke.assert_called_once()
        database.assert_not_called()

    def test_formatting_failures_cannot_be_waived(self):
        state = deepcopy(STATE)
        state["draft"]["text"] += " 👩🏽‍💻 #trial"
        state["writer_context"]["writing_preferences"] = {
            "word_range": "1-2", "emojis": "None", "hashtags": "None",
        }
        output, inputs, _, _ = self.run_review(state)
        self.assertEqual(output["writing_review"]["verdict"], "revise")
        self.assertEqual(len(output["writing_review"]["findings"]), 3)
        self.assertEqual(inputs["deterministic_checks"]["emoji_count"], 1)

    def test_stale_or_invalid_context_holds_without_model(self):
        for update in ({"writer_context": {}}, {"draft": {"text": TEXT}}):
            with self.subTest(update=update):
                output, _, chain, _ = self.run_review({**deepcopy(STATE), **update})
                self.assertEqual(output["writing_review"]["verdict"], "hold")
                chain.assert_not_called()

    def test_no_current_draft_skips_review(self):
        for state in ({}, {**deepcopy(STATE), "writer_status": "needs_material"}):
            output, _, chain, database = self.run_review(state)
            self.assertIsNone(output["writing_review"])
            chain.assert_not_called()
            database.assert_not_called()

    def test_personal_permissions_are_rechecked_without_research(self):
        state = deepcopy(STATE)
        state["draft"]["evidence_map"][0]["personal_material_ids"] = ["experience-1"]
        record = {"id": "experience-1", "usage_permission": "May use in drafts",
                  "permitted_details": ["Role"], "personal_role": "Teacher",
                  "outcome": "PRIVATE RESULT", "anonymisation": "Do not name the school."}
        profile = {"experiences": {"items": [record]}}
        _, inputs, _, _ = self.run_review(state, profile=profile)
        self.assertEqual(inputs["personal_material"][0]["personal_role"], "Teacher")
        self.assertNotIn("PRIVATE RESULT", json.dumps(inputs))
        record["usage_permission"] = "Private context only"
        output, inputs, _, _ = self.run_review(state, profile=profile)
        self.assertEqual(inputs["personal_material"], [])
        self.assertEqual(output["writing_review"]["verdict"], "revise")
        self.assertEqual(output["writing_review"]["findings"][0]["kind"], "personal_material")

    def test_missing_samples_does_not_block_or_add_history_notices(self):
        state = deepcopy(STATE)
        state["writer_context"]["writing_samples"] = []
        output, _, _, _ = self.run_review(state)
        self.assertEqual(output["writing_review"]["verdict"], "pass")
        self.assertEqual(len(output["writing_review"]["limitations"]), 1)
        self.assertIn("No eligible writing samples", output["writing_review"]["limitations"][0])

    def test_wrong_version_and_invented_spans_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "different draft version"):
            self.run_review(result={**PASS, "draft_version": 2})
        finding = {"kind": "voice", "severity": "major", "suggested_owner": "writer",
                   "draft_span": "Absent sentence", "evidence": "Short direct sentences requested.",
                   "required_change": "Split the sentence."}
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.run_review(result={**PASS, "verdict": "revise", "findings": [finding]})

    def test_research_findings_and_false_pass_are_not_valid(self):
        finding = {"kind": "voice", "severity": "major", "suggested_owner": "writer",
                   "draft_span": TEXT, "evidence": "Short direct sentences requested.",
                   "required_change": "Split the sentence."}
        for changes in ({"kind": "evidence"}, {"suggested_owner": "researcher"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                WritingReview.model_validate({**PASS, "verdict": "revise", "findings": [{**finding, **changes}]})
        with self.assertRaises(ValidationError):
            WritingReview.model_validate({**PASS, "findings": [finding]})


if __name__ == "__main__":
    unittest.main()
