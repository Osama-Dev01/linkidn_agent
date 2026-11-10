import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from app.catalog.preference_catalogue import CatalogueError
from app.services.preference_learning import PreferenceUpdates, learn_preferences


class PreferenceLearningTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "user_id": "user-1", "cycle_id": "run-1", "status": "published",
            "linkedin_post_id": "post-1", "draft_review_text": "Approved text",
            "voice": {"tone": ["Conversational"], "formality": "Balanced"},
            "formatting": {"emojis": "Occasional"},
            "topic_interests": {"primary_topics": ["Engineering", "Tools"]},
            "feedback_events": [
                {"user_id": "user-1", "run_id": "run-1", "stage": "topic_selection",
                 "feedback": "Focus future posts on engineering, not tools."},
                {"user_id": "user-1", "run_id": "run-1", "stage": "post_finalization",
                 "feedback": "Avoid emojis in future posts."},
            ],
        }
        self.original = deepcopy(self.state)
        database = patch("app.services.preference_learning.get_database")
        self.database = database.start().return_value
        self.addCleanup(database.stop)
        chain = patch("app.services.preference_learning._get_chain")
        self.chain = chain.start().return_value
        self.addCleanup(chain.stop)

    def updates(self, *items):
        self.chain.invoke.return_value = PreferenceUpdates(updates=list(items))

    def test_updates_preferences_without_saving_feedback_or_changing_profile(self):
        self.updates(
            {"field": "formatting/emojis", "operation": "set", "new_value": "None"},
            {"field": "topic_interests/primary_topics", "operation": "remove", "new_value": ["Tools"]},
            {"field": "anti_style/avoided_phrases", "operation": "add", "new_value": ["game changer"]},
        )
        result = learn_preferences(self.state)
        self.assertEqual(result["formatting"]["emojis"], "None")
        self.assertEqual(result["topic_interests"]["primary_topics"], ["Engineering"])
        self.assertEqual(result["anti_style"]["avoided_phrases"], ["game changer"])
        self.assertEqual(result["voice"], self.state["voice"])
        self.assertEqual(self.state, self.original)
        self.database.preferences.replace_one.assert_called_once_with(
            {"user_id": "user-1"}, {"user_id": "user-1", **result}, upsert=True,
        )
        self.assertEqual(len(self.database.mock_calls), 1)

    def test_model_can_choose_no_updates(self):
        self.updates()
        result = learn_preferences(self.state)
        self.assertEqual(result["voice"], self.state["voice"])
        self.assertEqual(result["formatting"], self.state["formatting"])
        self.assertEqual(result["topic_interests"], self.state["topic_interests"])

    def test_model_receives_all_preferences_and_only_this_users_run_feedback(self):
        self.state["feedback_events"] += [
            {"user_id": "user-2", "run_id": "run-1", "stage": "post_finalization", "feedback": "Private"},
            {"user_id": "user-1", "run_id": "old-run", "stage": "topic_selection", "feedback": "Old"},
        ]
        self.updates()
        learn_preferences(self.state)
        inputs = json.loads(self.chain.invoke.call_args.args[0]["learning_input"])
        self.assertEqual(len(inputs["feedback"]), 2)
        self.assertEqual(inputs["preferences"]["voice"], self.state["voice"])
        self.assertEqual(inputs["preferences"]["formatting"], self.state["formatting"])
        self.assertEqual(inputs["published_text"], "Approved text")

    def test_invalid_model_changes_are_not_saved(self):
        for change in (
            {"field": "formatting/emojis", "operation": "set", "new_value": "Invented"},
            {"field": "formatting/hashtag_max", "operation": "set", "new_value": -1},
            {"field": "identity/name", "operation": "set", "new_value": "Other"},
        ):
            with self.subTest(change=change):
                self.updates(change)
                with self.assertRaises(CatalogueError):
                    learn_preferences(self.state)
        self.database.preferences.replace_one.assert_not_called()

    def test_duplicate_field_changes_are_not_saved(self):
        change = {"field": "formatting/emojis", "operation": "set", "new_value": "None"}
        self.updates(change, change)
        with self.assertRaisesRegex(ValueError, "distinct fields"):
            learn_preferences(self.state)
        self.database.preferences.replace_one.assert_not_called()


if __name__ == "__main__":
    unittest.main()
