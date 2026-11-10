"""Integration tests use only a fresh, uniquely named MongoDB database."""
import os
import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from app.api import profile
from app.db.client import client, initialize_profile_indexes
from app.server import app

ORIGIN = {"Origin": "http://127.0.0.1:5173"}
IDENTITY = {"name": "Test Author", "professional_role": "Engineer", "industry": ["Technology"],
            "background": "Building prototypes", "public_positioning": "Share practical lessons", "default_speaker_role": "Learner"}


@unittest.skipUnless(os.getenv("RUN_DB_TESTS") == "1", "Set RUN_DB_TESTS=1 to run isolated MongoDB tests")
class ProfileApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_name = "author_studio_test_" + uuid4().hex
        cls.database = client[cls.database_name]
        initialize_profile_indexes(cls.database)
        cls.database_patch = patch.object(profile, "db", cls.database)
        cls.database_patch.start()
        cls.startup_patch = patch("app.server.initialize_database", lambda: None)
        cls.startup_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.startup_patch.stop()
        cls.database_patch.stop()
        client.drop_database(cls.database_name)

    def setUp(self):
        self.web = TestClient(app)
        self.email = uuid4().hex + "@example.test"
        self.credentials = {"email": self.email, "password": "A-test-password-492!"}
        result = self.web.post("/api/auth/register", json={**self.credentials, "name": "Tester"}, headers=ORIGIN)
        self.assertEqual(result.status_code, 201, result.text)
        self.auth = result.json()
        self.headers = {**ORIGIN, "X-CSRF-Token": self.auth["csrf"]}
        self.assertIn("HttpOnly", result.headers["set-cookie"])
        self.assertNotIn("password", result.text)

    def tearDown(self):
        self.web.close()

    def test_save_fetch_and_returning_login(self):
        result = self.web.put("/api/profile/identity", json=IDENTITY, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["sections"]["identity"], IDENTITY)
        self.assertEqual(self.web.get("/api/profile").json()["user_id"], self.auth["user"]["user_id"])
        self.assertEqual(self.web.post("/api/auth/logout", headers=self.headers).status_code, 200)
        self.assertEqual(self.web.get("/api/profile").status_code, 401)
        login = self.web.post("/api/auth/login", json=self.credentials, headers=ORIGIN)
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["user"]["user_id"], self.auth["user"]["user_id"])
        self.assertEqual(self.web.get("/api/profile").json()["sections"]["identity"], IDENTITY)

    def test_isolation_and_owner_spoofing(self):
        self.web.put("/api/profile/identity", json=IDENTITY, headers=self.headers)
        with TestClient(app) as second:
            # Lifespan is patched below to avoid initializing the application DB.
            auth = second.post("/api/auth/register", json={"name": "Other", "email": uuid4().hex + "@example.test", "password": "Another-password!"}, headers=ORIGIN).json()
            self.assertEqual(second.get("/api/profile").json()["sections"], {})
            result = second.put("/api/profile/identity", json={**IDENTITY, "user_id": self.auth["user"]["user_id"]}, headers={**ORIGIN, "X-CSRF-Token": auth["csrf"]})
            self.assertEqual(result.status_code, 422)
        self.assertEqual(self.web.get("/api/profile").json()["sections"]["identity"], IDENTITY)

    def test_invalid_fields_and_permissions(self):
        for body in [{}, {**IDENTITY, "name": "  "}, {**IDENTITY, "default_speaker_role": "Made up"}, {**IDENTITY, "language": "English"}]:
            self.assertEqual(self.web.put("/api/profile/identity", json=body, headers=self.headers).status_code, 422)
        self.assertEqual(self.web.put("/api/profile/expertise", json={}, headers=self.headers).status_code, 422)
        self.assertEqual(self.web.put("/api/profile/interests", json={"primary_topics": ["AI"], "preferred_content_types": ["Tutorial"], "freshness": "Timely"}, headers=self.headers).status_code, 422)
        self.assertEqual(self.web.put("/api/profile/stances", json={"items": [{"id": "x", "topic": "AI", "position": "Prefer workflows", "reasoning": "Debugging"}]}, headers=self.headers).status_code, 422)
        self.assertEqual(self.web.put("/api/profile/stances", json={"items": []}, headers=self.headers).status_code, 200)
        self.assertEqual(self.web.put("/api/profile/unknown", json={}, headers=self.headers).status_code, 404)

    def test_csrf_and_expired_session(self):
        self.assertEqual(self.web.put("/api/profile/identity", json=IDENTITY, headers=ORIGIN).status_code, 403)
        self.assertEqual(self.web.put("/api/profile/identity", json=IDENTITY, headers={**self.headers, "Origin": "https://evil.example"}).status_code, 403)
        self.database.auth_sessions.update_many({"user_id": self.auth["user"]["user_id"]}, {"$set": {"expires_at": profile.now() - timedelta(seconds=1)}})
        self.assertEqual(self.web.get("/api/profile").status_code, 401)

    def test_credentials_and_duplicate_email(self):
        duplicate = self.web.post("/api/auth/register", json={**self.credentials, "email": self.email.upper(), "name": "Tester"}, headers=ORIGIN)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.web.post("/api/auth/login", json={**self.credentials, "password": "Wrong-password"}, headers=ORIGIN).status_code, 401)
        invalid = self.web.post("/api/auth/register", json={"name": "Test", "email": "bad", "password": "secret"}, headers=ORIGIN)
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn('secret', invalid.text)
        stored = self.database.users.find_one({"email": self.email})
        self.assertNotEqual(stored["password_hash"], self.credentials["password"])

    def test_rate_limit(self):
        for _ in range(15):
            result = self.web.post("/api/auth/login", json={**self.credentials, "password": "Wrong-password"}, headers=ORIGIN)
        self.assertEqual(result.status_code, 429)


if __name__ == "__main__":
    unittest.main()
