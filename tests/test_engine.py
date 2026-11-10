import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app.api import profile
from app.services import engine


PROFILE = {
    "user_id": "author-1",
    "identity": {
        "name": "Test Author", "professional_role": "Engineer", "industry": ["Technology"],
        "background": "Building tools", "public_positioning": "Share practical lessons",
        "default_speaker_role": "Practitioner",
    },
    "expertise": {"experienced_topics": ["Software engineering"]},
    "audience": {
        "target_audience": ["Engineers"], "audience_level": "Intermediate",
        "audience_problems": ["Reliable workflows"], "posting_goals": ["Share knowledge"],
        "content_themes": ["Engineering", "Testing", "Tools"],
    },
    "interests": {
        "primary_topics": ["Software engineering"], "preferred_content_types": ["Tutorial"],
        "freshness": "Evergreen",
    },
    "preferences": {
        "tone": ["Conversational"], "formality": "Balanced", "point_of_view": "First person",
        "technical_depth": "Accessible", "preferred_opening": ["Question"],
        "preferred_organisation": ["Problem → solution"], "post_length": "Medium",
        "closing_style": ["Practical takeaway"], "paragraph_style": "Short",
        "lists": "When helpful", "emojis": "None", "hashtags": "None",
        "citations": "Sources at end", "repeat_policy": "Avoid repeats",
        "research_depth": "Standard", "minimum_sources": 2,
        "preferred_evidence": ["Official documentation"], "uncertain_claims": "Omit",
    },
    "writing_samples": {"items": []},
    "stances": {"items": []},
    "experiences": {"items": []},
}


class EngineApiTests(unittest.TestCase):
    def setUp(self):
        database = Mock()
        database.profiles.find_one.return_value = deepcopy(PROFILE)
        database.engine_runs.find_one.return_value = None
        self.database = database
        for name, value in (
            ("db", database),
            ("get_session", Mock(return_value={"user_id": "author-1", "csrf_token": "csrf-1"})),
            ("run_engine_task", Mock()),
        ):
            patcher = patch.object(profile, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(profile.router)
        self.web = TestClient(app)
        self.addCleanup(self.web.close)
        self.headers = {"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": "csrf-1"}

    def test_complete_profile_starts_engine_for_session_user(self):
        response = self.web.post("/api/engine/run", headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        self.database.profiles.find_one.assert_called_once_with({"user_id": "author-1"}, {"_id": 0})
        profile.run_engine_task.assert_called_once_with(PROFILE)
        self.database.engine_runs.insert_one.assert_called_once_with({"_id": "author-1"})

    def test_missing_profile_or_section_does_not_start_engine(self):
        for section in (None, *PROFILE.keys() - {"user_id"}):
            with self.subTest(section=section):
                saved = deepcopy(PROFILE) if section else None
                if section:
                    del saved[section]
                self.database.profiles.find_one.return_value = saved
                response = self.web.post("/api/engine/run", headers=self.headers)
                self.assertEqual(response.status_code, 422)
                self.assertIn("Complete your profile first", response.json()["detail"])
        profile.run_engine_task.assert_not_called()

    def test_invalid_saved_fields_do_not_start_engine(self):
        self.database.profiles.find_one.return_value["identity"]["name"] = ""
        self.assertEqual(self.web.post("/api/engine/run", headers=self.headers).status_code, 422)
        profile.run_engine_task.assert_not_called()

    def test_missing_csrf_does_not_start_engine(self):
        self.assertEqual(self.web.post("/api/engine/run").status_code, 403)
        self.database.profiles.find_one.assert_not_called()
        profile.run_engine_task.assert_not_called()

    def test_unauthenticated_request_does_not_start_engine(self):
        profile.get_session.side_effect = HTTPException(status_code=401, detail="Authentication required.")
        self.assertEqual(self.web.post("/api/engine/run", headers=self.headers).status_code, 401)
        self.database.profiles.find_one.assert_not_called()
        profile.run_engine_task.assert_not_called()

    def test_client_cannot_choose_another_users_profile(self):
        response = self.web.post("/api/engine/run", json={"user_id": "author-2"}, headers=self.headers)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(profile.run_engine_task.call_args.args[0]["user_id"], "author-1")

    def test_running_engine_rejects_another_request_without_touching_current_run(self):
        self.database.engine_runs.find_one.return_value = {"_id": "author-1"}
        response = self.web.post("/api/engine/run", headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Engine currently running", response.json()["detail"])
        self.database.profiles.find_one.assert_not_called()
        self.database.engine_runs.insert_one.assert_not_called()
        self.database.engine_runs.delete_one.assert_not_called()
        profile.run_engine_task.assert_not_called()

    def test_simultaneous_start_losing_atomic_claim_does_not_start_another_engine(self):
        self.database.engine_runs.insert_one.side_effect = DuplicateKeyError("Already running")
        response = self.web.post("/api/engine/run", headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Engine currently running", response.json()["detail"])
        self.database.engine_runs.delete_one.assert_not_called()
        profile.run_engine_task.assert_not_called()

    def test_another_users_running_engine_does_not_block_this_user(self):
        self.database.engine_runs.find_one.side_effect = lambda query: (
            {"_id": "author-2"} if query["_id"] == "author-2" else None
        )
        self.assertEqual(self.web.post("/api/engine/run", headers=self.headers).status_code, 202)
        profile.run_engine_task.assert_called_once_with(PROFILE)


class EngineRunTests(unittest.TestCase):
    def test_running_marker_remains_during_execution_and_is_removed_after_completion(self):
        with patch.object(engine, "get_database") as database, patch.object(engine, "run_engine") as run:
            def execute(saved):
                database.return_value.engine_runs.delete_one.assert_not_called()
                return {"status": "published"}
            run.side_effect = execute
            self.assertEqual(engine.run_engine_task(PROFILE), {"status": "published"})
            database.return_value.engine_runs.delete_one.assert_called_once_with({"_id": "author-1"})

    def test_failed_run_releases_marker_so_user_can_run_again(self):
        with patch.object(engine, "get_database") as database, patch.object(
            engine, "run_engine", side_effect=RuntimeError("Engine failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Engine failed"):
                engine.run_engine_task(PROFILE)
            database.return_value.engine_runs.delete_one.assert_called_once_with({"_id": "author-1"})


class EnginePreferencesTests(unittest.TestCase):
    def test_saved_preferences_are_mapped_before_running_graph(self):
        saved = deepcopy(PROFILE)
        with patch.object(engine, "get_database") as database, patch.object(
            engine, "run_graph", return_value={"status": "done"},
        ) as run:
            database.return_value.preferences.find_one.return_value = None
            result = engine.run_engine(saved)
        self.assertEqual(result, {"status": "done"})
        user_id, preferences = run.call_args.args
        self.assertEqual(user_id, "author-1")
        self.assertEqual(preferences["topic_interests"]["primary_topics"], ["Software engineering"])
        self.assertEqual(preferences["voice"]["tone"], ["Conversational"])
        self.assertEqual(saved, PROFILE)
        database.return_value.preferences.replace_one.assert_called_once_with(
            {"user_id": "author-1"}, {"user_id": "author-1", **preferences}, upsert=True,
        )

    def test_existing_preferences_are_loaded_without_mapping_profile(self):
        preferences = {"voice": {"tone": ["Direct"]}}
        with patch.object(engine, "get_database") as database, patch.object(
            engine, "load_preferences",
        ) as load, patch.object(engine, "run_graph") as run:
            database.return_value.preferences.find_one.return_value = preferences
            engine.run_engine(deepcopy(PROFILE))
        load.assert_not_called()
        database.return_value.preferences.replace_one.assert_not_called()
        database.return_value.preferences.find_one.assert_called_once_with(
            {"user_id": "author-1"}, {"_id": 0, "user_id": 0},
        )
        run.assert_called_once_with("author-1", preferences)


if __name__ == "__main__":
    unittest.main()
