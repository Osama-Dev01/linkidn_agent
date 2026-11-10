import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.agents.briefer import EditorialBrief, create_brief


BRIEF = {
    "content_type": "Tutorial",
    "speaker_role": "Learner",
    "central_question": "Which capabilities does this task need?",
    "provisional_angle": "Compare two examples with different levels of autonomy.",
    "research_questions": ["Find two documented examples and their deployment status."],
}


class BrieferTests(unittest.TestCase):
    def test_brief_accepts_one_or_two_questions_and_rejects_expanded_shape(self):
        EditorialBrief.model_validate(BRIEF)
        EditorialBrief.model_validate({**BRIEF, "research_questions": ["First?", "Second?"]})
        for changes in (
            {"research_questions": []},
            {"research_questions": ["First?", "Second?", "Third?"]},
            {"intended_reader": "Engineers"},
            {"intended_takeaway": "Choose the simplest approach."},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                EditorialBrief.model_validate({**BRIEF, **changes})

    def test_create_brief_uses_audience_context_without_repeating_it(self):
        state = {
            "user_id": "user-1", "cycle_id": "run-1",
            "selected_topic": {"id": "source-1", "title": "Agentic capabilities"},
            "sources": [{"id": "source-1", "summary": "Source summary.", "body": "Full source body."}],
        }
        with patch("app.agents.briefer.get_database") as database, patch(
            "app.agents.briefer._get_chain",
        ) as chain, patch("builtins.print"):
            database.return_value.profiles.find_one.return_value = {
                "audience": {"target_audience": ["Engineers"], "audience_level": "Intermediate"},
            }
            chain.return_value.invoke.return_value = EditorialBrief.model_validate(BRIEF)
            result = create_brief(state)
        inputs = json.loads(chain.return_value.invoke.call_args.args[0]["brief_input"])
        self.assertEqual(inputs["target_audience"], ["Engineers"])
        self.assertEqual(inputs["source_summary"], "Source summary.")
        self.assertNotIn("Full source body.", json.dumps(inputs))
        self.assertEqual(result["brief"], {"selected_source_id": "source-1", **BRIEF})
        self.assertEqual(result["brief_status"], "ready_for_research")

    def test_missing_topic_or_summary_does_not_call_model(self):
        with patch("app.agents.briefer._get_chain") as chain:
            self.assertEqual(create_brief({}), {})
            self.assertEqual(create_brief({
                "selected_topic": {"id": "source-1", "title": "Topic"},
                "sources": [{"id": "source-1", "summary": " "}],
            }), {"brief": None, "brief_status": "needs_source"})
            chain.assert_not_called()


if __name__ == "__main__":
    unittest.main()
