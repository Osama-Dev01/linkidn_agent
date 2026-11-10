import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import profile
from app.services.linkedin import publish_approved_post


class PublishedPostStorageTests(unittest.TestCase):
    def test_saves_exact_published_text_and_owner_after_success(self):
        state = {
            "user_id": "author-1", "cycle_id": "run-1",
            "selected_topic": {"title": "Engineering lessons"},
            "draft_review_text": "First paragraph.\n\nSecond paragraph.",
        }
        with patch("app.services.linkedin.publish_post", return_value="post-1") as publish, patch(
            "app.services.linkedin.get_database",
        ) as database:
            result = publish_approved_post(state)
        saved = database.return_value.published_posts.insert_one.call_args.args[0]
        self.assertEqual(saved["user_id"], "author-1")
        self.assertEqual(saved["run_id"], "run-1")
        self.assertEqual(saved["post_id"], "post-1")
        self.assertEqual(saved["title"], "Engineering lessons")
        self.assertEqual(saved["final_text"], publish.call_args.args[0])
        self.assertEqual(saved["final_text"], "Engineering lessons\n\nFirst paragraph.\n\nSecond paragraph.")
        self.assertIsNotNone(saved["published_at"].tzinfo)
        self.assertEqual(result["status"], "published")

    def test_autonomous_post_content_is_saved_without_adding_topic_title(self):
        state = {
            "user_id": "author-1", "cycle_id": "run-1", "autonomous_active": True,
            "selected_topic": {"title": "Topic title"},
            "draft": {"version": 2, "text": "Approved content."},
            "draft_review_version": 2, "draft_review_text": "Approved content.",
            "draft_review_decision": "approve",
        }
        with patch("app.services.linkedin.review_is_current", return_value=True), patch(
            "app.services.linkedin.publish_post", return_value="post-1",
        ), patch("app.services.linkedin.get_database") as database:
            publish_approved_post(state)
        saved = database.return_value.published_posts.insert_one.call_args.args[0]
        self.assertEqual(saved["title"], "Topic title")
        self.assertEqual(saved["final_text"], "Approved content.")

    def test_failed_publication_does_not_save_a_post(self):
        with patch("app.services.linkedin.publish_post", side_effect=RuntimeError("Failed")), patch(
            "app.services.linkedin.get_database",
        ) as database:
            with self.assertRaisesRegex(RuntimeError, "Failed"):
                publish_approved_post({"draft_review_text": "Draft"})
        database.assert_not_called()


class PublishedPostsApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(profile.router)
        self.web = TestClient(app)
        self.addCleanup(self.web.close)

    def test_returns_only_session_users_posts_newest_first(self):
        posts = [{"post_id": "post-1", "title": "Title", "final_text": "Content"}]
        with patch.object(profile, "get_session", return_value={"user_id": "author-1"}), patch.object(
            profile, "db",
        ) as database:
            database.published_posts.find.return_value.sort.return_value = posts
            result = self.web.get("/api/published-posts?user_id=author-2")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"posts": posts})
        database.published_posts.find.assert_called_once_with(
            {"user_id": "author-1"},
            {"_id": 0, "post_id": 1, "title": 1, "final_text": 1, "published_at": 1},
        )
        database.published_posts.find.return_value.sort.assert_called_once_with("published_at", -1)

    def test_no_published_posts_returns_empty_list(self):
        with patch.object(profile, "get_session", return_value={"user_id": "author-1"}), patch.object(
            profile, "db",
        ) as database:
            database.published_posts.find.return_value.sort.return_value = []
            self.assertEqual(self.web.get("/api/published-posts").json(), {"posts": []})

    def test_authentication_is_required(self):
        with patch.object(profile, "get_session", side_effect=HTTPException(status_code=401)), patch.object(
            profile, "db",
        ) as database:
            self.assertEqual(self.web.get("/api/published-posts").status_code, 401)
        database.published_posts.find.assert_not_called()


if __name__ == "__main__":
    unittest.main()
