import json
import unittest
from contextlib import ExitStack
from copy import deepcopy
from importlib import import_module
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.search_topics import SearchQueries
from app.agents.summarizer import UserSummary
from app.services.send_mail import parse_topic_reply, wait_for_reply


def record(title, source="web"):
    return {"title": title, "description": f"Description of {title}", "body": f"Body of {title}",
            "url": f"https://example.org/{title.lower()}", "source": source,
            "matched_topics": ["Education"]}


class ProductionTopicReviewTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("builtins.print"))
        self.stack.enter_context(patch("app.db.client.get_checkpointer", return_value=InMemorySaver()))
        module = import_module("app.graph.builder")
        self.graph = module.builder.compile(checkpointer=InMemorySaver(), interrupt_before=["summarize_topic"])
        database = self.stack.enter_context(patch("app.services.send_mail.get_database")).return_value
        database.users.find_one.side_effect = lambda query: {"email": f"{query['user_id']}@example.org"}
        profile_database = self.stack.enter_context(patch("app.agents.summarizer.get_database")).return_value
        profile_database.profiles.find_one.return_value = {}
        summary = self.stack.enter_context(patch("app.agents.summarizer.ChatOpenAI"))
        summary.return_value.with_structured_output.return_value = RunnableLambda(
            lambda _: UserSummary(lines=[f"Writing context {index}" for index in range(7)])
        )
        self.search_inputs = []
        self.filter_inputs = []
        self.collections = []
        self.emails = []
        self.batches = [[record("First"), record("Hidden"), record("Discussion", "hackernews"),
                         record("Newsletter", "substack")]]
        self.filter_plans = []
        search = self.stack.enter_context(patch("app.agents.search_topics._get_chain"))
        search.return_value.invoke.side_effect = self.generate_queries
        filtering = self.stack.enter_context(patch("app.agents.topic_review_agent._get_chain"))
        filtering.return_value.invoke.side_effect = self.choose_candidates
        for source, module_name in (("web", "web_search"), ("hackernews", "hacker_news"), ("substack", "substack")):
            collector = self.stack.enter_context(patch(f"app.services.{module_name}.collect_with_timeout"))
            collector.side_effect = lambda module, name, state, source=source: self.collect(source, state)
        self.stack.enter_context(patch("app.services.send_mail.send_email", side_effect=self.send_email))
        self.config = {"configurable": {"thread_id": self.id()}, "recursion_limit": 100}

    def generate_queries(self, inputs):
        self.search_inputs.append(deepcopy(inputs))
        batch = len(self.search_inputs)
        return SearchQueries(queries=[f"education {batch} {index}" for index in range(10)])

    def choose_candidates(self, inputs):
        selection = json.loads(inputs["selection_input"])
        self.filter_inputs.append(selection)
        titles = self.filter_plans.pop(0) if self.filter_plans else None
        return {"selected_source_ids": [item["id"] for item in selection["candidates"]
                                        if titles is None or item["title"] in titles]}

    def collect(self, source, state):
        self.collections.append((source, deepcopy(state)))
        batch = self.batches[min(len(self.search_inputs) - 1, len(self.batches) - 1)]
        return {"raw_sources": deepcopy([item for item in batch if item["source"] == source])}

    def send_email(self, recipient, subject, html, text):
        self.emails.append({"recipient": recipient, "subject": subject, "html": html, "text": text})
        return f"<email-{len(self.emails)}>"

    def start(self, user="user-1", config=None):
        return self.graph.invoke({
            "user_id": user, "cycle_id": f"run-{user}", "topic_interests": {"primary_topics": ["Education"]},
            "feedback_events": [], "feedback": "", "requested_angle": "", "rejected_topic_ids": [],
            "topic_retry_count": 0, "raw_sources": [], "search_querries": [],
        }, config or self.config)

    def reply(self, text, config=None):
        return self.graph.invoke(Command(resume={"reply_id": f"<reply-{len(self.emails)}>", "reply": text}),
                                 config or self.config)

    def assert_waiting(self, result):
        self.assertTrue(result.get("__interrupt__"))
        self.assertEqual(result["__interrupt__"][0].value["type"], "topic_email_review")
        self.assertFalse(result.get("selected_topic"))
        self.assertNotIn("brief", result)
        self.assertNotIn("draft", result)

    def test_initial_discovery_joins_all_collectors_and_sends_one_review(self):
        result = self.start()
        self.assert_waiting(result)
        self.assertEqual(len(result["topics"]), 4)
        self.assertEqual(len(self.collections), 3)
        self.assertEqual(len(self.emails), 1)
        self.assertEqual(self.emails[0]["recipient"], "user-1@example.org")
        self.assertIn("Select: 2", self.emails[0]["text"])
        self.assertEqual(len(result["search_querries"]), 10)

    def test_selection_with_feedback_and_angle_stops_before_summary(self):
        initial = self.start()
        selected = initial["topics"][1]
        result = self.reply("Select: 2\nFeedback: Explain limitations.\nAngle: Compare alternatives")
        self.assertEqual(result["selected_topic"], selected)
        self.assertEqual([source["id"] for source in result["sources"]], [selected["id"]])
        self.assertEqual(result["feedback"], "Explain limitations.")
        self.assertEqual(result["requested_angle"], "Compare alternatives")
        self.assertEqual(self.graph.get_state(self.config).next, ("summarize_topic",))
        self.assertEqual(len(self.emails), 1)
        self.assertNotIn("draft", result)

    def test_rejection_recollects_replaces_queries_and_excludes_same_urls(self):
        first = self.start()
        rejected = {topic["id"] for topic in first["topics"]}
        self.batches.append([*self.batches[0], record("Fresh")])
        result = self.reply("Reject all\nFeedback: Find concrete classroom examples.\nAngle: Practical lessons")
        self.assert_waiting(result)
        self.assertEqual([topic["title"] for topic in result["topics"]], ["Fresh"])
        self.assertEqual(set(result["rejected_topic_ids"]), rejected)
        self.assertTrue(rejected.isdisjoint({item["id"] for item in self.filter_inputs[-1]["candidates"]}))
        self.assertEqual(len(result["raw_sources"]), 5)
        self.assertEqual(len(result["search_querries"]), 10)
        self.assertTrue(all(query.startswith("education 2 ") for query in result["search_querries"]))
        self.assertIn("Find concrete classroom examples.", self.search_inputs[-1]["review_context"])
        self.assertIn("Practical lessons", self.search_inputs[-1]["review_context"])
        self.assertEqual(len(self.collections), 6)
        self.assertEqual(len(self.emails), 2)

    def test_feedback_can_recover_unshown_candidates_without_recollecting(self):
        self.filter_plans = [["First"], ["Hidden"]]
        first = self.start()
        self.assertEqual([topic["title"] for topic in first["topics"]], ["First"])
        result = self.reply("Feedback: Prefer concrete examples.\nAngle: Compare alternatives")
        self.assert_waiting(result)
        self.assertEqual([topic["title"] for topic in result["topics"]], ["Hidden"])
        self.assertEqual(len(self.search_inputs), 1)
        self.assertEqual(len(self.collections), 3)
        self.assertEqual(len(self.filter_inputs[-1]["candidates"]), 4)
        self.assertEqual(self.filter_inputs[-1]["feedback"], "Prefer concrete examples.")
        self.assertEqual(self.filter_inputs[-1]["requested_angle"], "Compare alternatives")
        self.assertEqual(result["rejected_topic_ids"], [])
        selected = self.reply("Select: 1")
        self.assertEqual(selected["feedback"], "Prefer concrete examples.")
        self.assertEqual(selected["requested_angle"], "Compare alternatives")

    def test_empty_collection_pauses_then_direction_restarts_discovery(self):
        self.batches = [[], [record("Fresh")]]
        first = self.start()
        self.assert_waiting(first)
        self.assertEqual(first["status"], "awaiting_topic_direction")
        self.assertEqual(first["topics"], [])
        self.assertEqual(len(self.filter_inputs), 0)
        result = self.reply("Feedback: Focus on teaching methods.")
        self.assert_waiting(result)
        self.assertEqual([topic["title"] for topic in result["topics"]], ["Fresh"])
        self.assertEqual(result["topic_retry_count"], 0)

    def test_empty_refilter_pauses_without_starting_unrequested_research(self):
        self.filter_plans = [["First"], []]
        self.start()
        result = self.reply("Feedback: These examples are unsuitable.")
        self.assert_waiting(result)
        self.assertEqual(result["status"], "awaiting_topic_direction")
        self.assertEqual(len(self.search_inputs), 1)
        self.assertEqual(len(self.emails), 2)

    def test_three_retries_then_direction_request_without_fourth_search(self):
        self.batches = [[record(f"Batch-{index}")] for index in range(5)]
        self.start()
        for index in range(3):
            result = self.reply("Reject all\nTry different examples.")
            self.assert_waiting(result)
            self.assertEqual(result["topic_retry_count"], index + 1)
            self.assertEqual(result["status"], "awaiting_topic_review")
        result = self.reply("Reject all\nStill unsuitable.")
        self.assert_waiting(result)
        self.assertEqual(result["status"], "awaiting_topic_direction")
        self.assertEqual(len(self.search_inputs), 4)
        self.assertEqual(len(self.emails), 5)
        self.assertIn("retry limit", self.emails[-1]["text"])
        result = self.reply("Feedback: Focus on lesson planning.")
        self.assert_waiting(result)
        self.assertEqual(result["topic_retry_count"], 0)
        self.assertEqual(len(self.search_inputs), 5)

    def test_independent_users_do_not_share_rejections_or_feedback(self):
        self.batches.append([*self.batches[0], record("Fresh")])
        first = self.start()
        rejected = {topic["id"] for topic in first["topics"]}
        self.reply("Reject all\nOnly classroom examples.")
        other_config = {"configurable": {"thread_id": f"{self.id()}-other"}, "recursion_limit": 100}
        other = self.start("user-2", other_config)
        self.assertEqual(other["feedback"], "")
        self.assertEqual(other["rejected_topic_ids"], [])
        self.assertEqual(other["feedback_events"], [])
        self.assertEqual(self.emails[-1]["recipient"], "user-2@example.org")
        self.assertTrue(rejected.isdisjoint({topic["id"] for topic in other["topics"]}))

    def test_server_runner_handles_rejection_feedback_and_selection(self):
        self.batches.append([record("Fresh"), record("Hidden-fresh")])
        self.filter_plans = [["First"], ["Fresh"], ["Hidden-fresh"]]
        engine = import_module("app.services.engine")
        replies = [
            {"reply_id": "<reject>", "reply": "Reject all\nFind classroom examples."},
            {"reply_id": "<feedback>", "reply": "Feedback: More practical.\nAngle: Compare alternatives"},
            {"reply_id": "<select>", "reply": "Select: 1"},
        ]
        with patch("app.graph.builder.graph", self.graph), patch(
            "app.services.engine.wait_for_reply", side_effect=replies,
        ) as poll:
            result = engine.run_graph("user-1", {"topic_interests": {"primary_topics": ["Education"]}})
        self.assertEqual(result["selected_topic"]["title"], "Hidden-fresh")
        self.assertEqual(result["requested_angle"], "Compare alternatives")
        self.assertEqual(result["feedback"], "Find classroom examples.\nMore practical.")
        self.assertEqual(len(result["feedback_events"]), 3)
        self.assertEqual(poll.call_count, 3)
        self.assertEqual(len(self.search_inputs), 2)
        self.assertEqual(len(self.emails), 3)

    def test_timeout_keeps_checkpoint_but_new_runner_call_starts_new_cycle(self):
        engine = import_module("app.services.engine")
        preferences = {"topic_interests": {"primary_topics": ["Education"]}}
        with patch("app.graph.builder.graph", self.graph), patch("app.services.engine.wait_for_reply", return_value=None):
            first = engine.run_graph("user-1", preferences)
            second = engine.run_graph("user-1", preferences)
        self.assert_waiting(first)
        self.assert_waiting(second)
        self.assertNotEqual(first["cycle_id"], second["cycle_id"])
        original_config = {"configurable": {"thread_id": f"user-1:{first['cycle_id']}"}}
        self.assertEqual(self.graph.get_state(original_config).next, ("receive_topic_review",))
        self.assertEqual(len(self.emails), 2)


class TopicPollingTests(unittest.TestCase):
    def test_invalid_selection_is_ignored_then_feedback_is_collected(self):
        valid = {"reply_id": "<valid>", "reply": "Feedback: More practical examples."}
        with patch("app.services.send_mail.fetch_reply", side_effect=[
            {"reply_id": "<invalid>", "reply": "Select: 99"}, valid,
        ]) as fetch, patch("app.services.send_mail.time.monotonic", side_effect=[0, 1, 2, 3]), patch(
            "app.services.send_mail.time.sleep",
        ), patch("app.services.send_mail.logger"):
            result = wait_for_reply("<topics>", "user@example.org", [{"id": "a", "title": "First"}], timeout_s=10)
        self.assertEqual(result, valid)
        self.assertIn("<invalid>", fetch.call_args.args[2])

    def test_timeout_does_not_select_any_topic(self):
        with patch("app.services.send_mail.fetch_reply") as fetch, patch(
            "app.services.send_mail.time.monotonic", side_effect=[0, 11],
        ):
            self.assertIsNone(wait_for_reply("<topics>", "user@example.org", [], timeout_s=10))
            fetch.assert_not_called()

    def test_invalid_or_ambiguous_first_lines_are_not_selections(self):
        for reply in ("", "Select: 0", "Select: -1", "Select: 2", "I like the first one", "Angle: Compare"):
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                parse_topic_reply(reply, [{"id": "a", "title": "First"}])

    def test_conflicting_commands_currently_follow_first_line(self):
        topics = [{"id": "a", "title": "First"}]
        result = parse_topic_reply("Select: 1\nReject all", topics)
        self.assertEqual(result["action"], "select")
        self.assertEqual(result["selected_topic"], topics[0])
        self.assertEqual(result["feedback"], "Reject all")


if __name__ == "__main__":
    unittest.main()
