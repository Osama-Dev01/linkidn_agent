import json
import unittest
from copy import deepcopy
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agents.briefer import EditorialBrief, create_brief
from app.agents.search_topics import search_topics
from app.agents.topic_review_agent import filter_topics
from app.agents.topic_summarizer import TopicSummary, summarize_topic
from app.graph.state import ResearchState
from app.services.send_mail import parse_topic_reply, receive_topic_review, send_topic_direction
from app.services.topic_review import initail_states, route_after_filter, route_after_review
from tests.test_briefer import BRIEF


SOURCES = [
    {"id": "a", "title": "First subject", "description": "First description", "body": "First body"},
    {"id": "b", "title": "Second subject", "description": "Second description", "body": "Second body"},
]
TOPICS = [{"id": source["id"], "title": source["title"]} for source in SOURCES]
STATE = {
    "user_id": "user-1", "cycle_id": "run-1", "sources": SOURCES,
    "topic_candidates": SOURCES, "topics": TOPICS, "feedback_events": [],
    "topic_review_message_id": "<topics>", "topic_review_recipient": "user@example.org",
    "status": "awaiting_topic_review", "rejected_topic_ids": [],
}


class TopicReplyTests(unittest.TestCase):
    def test_commands_are_separate_from_feedback_and_angle(self):
        for reply, action, feedback, angle in (
            ("Select: 2", "select", "", ""),
            ("1\nFeedback: Explain limitations.\nUse an example.\nAngle: Compare alternatives",
             "select", "Explain limitations.\nUse an example.", "Compare alternatives"),
            ("Reject all\nFeedback: Too broad.", "reject", "Too broad.", ""),
            ("Feedback: More practical topics.\nAngle: Compare alternatives",
             "feedback", "More practical topics.", "Compare alternatives"),
            ("Revise: More practical topics.", "feedback", "More practical topics.", ""),
        ):
            with self.subTest(reply=reply):
                result = parse_topic_reply(reply, TOPICS)
                self.assertEqual((result["action"], result["feedback"], result["angle"]),
                                 (action, feedback, angle))
                self.assertEqual(result["raw_reply"], reply)
                self.assertEqual(result["selected_topic"],
                                 TOPICS[1 if reply.startswith("Select: 2") else 0] if action == "select" else None)

    def test_direction_requires_actionable_feedback(self):
        for reply in ("Select: 1", "Reject all", "Feedback:"):
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                parse_topic_reply(reply, [])
        self.assertEqual(parse_topic_reply("Feedback: Focus on education.", [])["feedback"],
                         "Focus on education.")
        with self.assertRaises(ValueError):
            parse_topic_reply("Feedback:", TOPICS)

    def test_selection_preserves_prior_run_feedback_and_angle(self):
        state = {**deepcopy(STATE), "feedback": "Focus on practical examples.",
                 "requested_angle": "Compare alternatives"}
        original = deepcopy(state)
        with patch("app.services.send_mail.interrupt", return_value={
            "reply_id": "<reply>", "reply": "Select: 2\nFeedback: Keep it simple.",
        }), patch("builtins.print"):
            result = receive_topic_review(state)
        self.assertEqual(result["sources"], [SOURCES[1]])
        self.assertEqual(result["decision"], "selected")
        self.assertEqual(result["feedback"], "Focus on practical examples.\nKeep it simple.")
        self.assertEqual(result["requested_angle"], "Compare alternatives")
        event = result["feedback_events"][0]
        self.assertEqual(event["scope"], "this_post")
        self.assertEqual(event["feedback"], "Keep it simple.")
        self.assertEqual(event["reply_id"], "<reply>")
        self.assertEqual(state, original)


class TopicRoutingTests(unittest.TestCase):
    def make_graph(self):
        fresh_sources = [{**source, "id": f"new-{source['id']}"} for source in SOURCES]
        fresh_topics = [{"id": source["id"], "title": source["title"]} for source in fresh_sources]
        builder = StateGraph(ResearchState)
        builder.add_node("receive_topic_review", receive_topic_review)
        builder.add_node("send_topic_direction", send_topic_direction)
        builder.add_node("search_topics", lambda state: {
            "status": "searched", "topics": fresh_topics,
            "sources": fresh_sources, "topic_candidates": fresh_sources,
        })
        builder.add_node("filter_topics", lambda state: {"status": "refiltered", "topics": fresh_topics})
        builder.add_node("summarize_topic", lambda state: {"status": "selected_for_summary"})
        builder.add_edge(START, "receive_topic_review")
        builder.add_conditional_edges("receive_topic_review", route_after_review, {
            name: name for name in ("search_topics", "filter_topics", "summarize_topic", "send_topic_direction")
        })
        builder.add_edge("send_topic_direction", "receive_topic_review")
        builder.add_edge("search_topics", "receive_topic_review")
        builder.add_edge("filter_topics", "receive_topic_review")
        builder.add_edge("summarize_topic", END)
        return builder.compile(checkpointer=InMemorySaver())

    def test_rejection_feedback_limit_direction_and_selection(self):
        graph = self.make_graph()
        config = {"configurable": {"thread_id": "topic-review"}, "recursion_limit": 100}
        with patch("app.services.send_mail.get_database") as database, patch(
            "app.services.send_mail.send_email", return_value="<direction>",
        ) as send, patch("builtins.print"):
            database.return_value.users.find_one.return_value = {"email": "user@example.org"}
            graph.invoke(deepcopy(STATE), config)
            for index in range(4):
                reply = "Reject all\nToo broad." if index == 0 else "Feedback: More practical."
                result = graph.invoke(Command(resume={"reply_id": str(index), "reply": reply}), config)
                self.assertTrue(result.get("__interrupt__"))
                self.assertIsNone(result["selected_topic"])
                if index < 3:
                    self.assertEqual(result["status"], "searched" if index == 0 else "refiltered")
            self.assertEqual(result["status"], "awaiting_topic_direction")
            self.assertEqual(result["__interrupt__"][0].value["topics"], [])
            send.assert_called_once()
            result = graph.invoke(Command(resume={
                "reply_id": "direction", "reply": "Feedback: Focus on teaching methods.",
            }), config)
            self.assertEqual(result["status"], "searched")
            self.assertEqual(result["topic_retry_count"], 0)
            result = graph.invoke(Command(resume={"reply_id": "selected", "reply": "Select: 1"}), config)
        self.assertEqual(result["status"], "selected_for_summary")
        self.assertEqual(result["selected_topic"]["id"], "new-a")
        self.assertEqual(result["rejected_topic_ids"], ["a", "b"])
        self.assertFalse(result.get("__interrupt__"))

    def test_empty_choices_request_direction_and_wait(self):
        self.assertEqual(route_after_filter({"topics": []}), "send_topic_direction")
        self.assertEqual(route_after_filter(STATE), "send_topic_review")
        graph = self.make_graph()
        config = {"configurable": {"thread_id": "no-topics"}}
        with patch("app.services.send_mail.get_database") as database, patch(
            "app.services.send_mail.send_email", return_value="<direction>",
        ), patch("builtins.print"):
            database.return_value.users.find_one.return_value = {"email": "user@example.org"}
            pending = send_topic_direction({**STATE, "topics": []})
            result = graph.invoke({**deepcopy(STATE), **pending}, config)
        self.assertEqual(result["status"], "awaiting_topic_direction")
        self.assertTrue(result.get("__interrupt__"))

    def test_production_graph_has_review_branches(self):
        with patch("app.db.client.get_checkpointer", return_value=InMemorySaver()):
            graph = import_module("app.graph.builder").graph.get_graph()
        edges = {(edge.source, edge.target) for edge in graph.edges}
        for target in ("summarize_topic", "search_topics", "filter_topics", "send_topic_direction"):
            self.assertIn(("receive_topic_review", target), edges)
        self.assertIn(("filter_topics", "send_topic_direction"), edges)
        self.assertIn(("send_topic_direction", "receive_topic_review"), edges)


class FeedbackHandoffTests(unittest.TestCase):
    def test_refilter_uses_full_pool_and_excludes_rejected_choices(self):
        state = {**deepcopy(STATE), "sources": [SOURCES[0]], "feedback": "Use concrete cases.",
                 "requested_angle": "Compare alternatives", "rejected_topic_ids": ["a"]}
        with patch("app.agents.topic_review_agent._get_chain") as chain, patch("builtins.print"):
            chain.return_value.invoke.return_value = {"selected_source_ids": ["b"]}
            result = filter_topics(state)
        inputs = json.loads(chain.return_value.invoke.call_args.args[0]["selection_input"])
        self.assertEqual([item["id"] for item in inputs["candidates"]], ["b"])
        self.assertEqual(inputs["feedback"], state["feedback"])
        self.assertEqual(inputs["requested_angle"], state["requested_angle"])
        self.assertEqual(result["sources"], [SOURCES[1]])

    def test_new_search_replaces_old_queries_and_receives_feedback(self):
        state = {**deepcopy(STATE), "topic_interests": {"primary_topics": ["Education"]},
                 "feedback": "Use concrete cases.", "requested_angle": "Compare alternatives",
                 "search_querries": ["old query"], "rejected_topic_ids": ["a"],
                 "feedback_events": [{"stage": "topic_selection", "run_id": "run-1",
                                      "topic_decisions": [{"topic_id": "a", "title": "First subject"}]}]}
        queries = [f"new query {index}" for index in range(10)]
        with patch("app.agents.search_topics._get_chain") as chain, patch("builtins.print"):
            chain.return_value.invoke.return_value = SimpleNamespace(queries=queries)
            builder = StateGraph(ResearchState)
            builder.add_node("search", search_topics)
            builder.add_node("reset", initail_states)
            builder.add_edge(START, "search")
            builder.add_edge("search", "reset")
            builder.add_edge("reset", END)
            result = builder.compile().invoke(state)
        context = chain.return_value.invoke.call_args.args[0]["review_context"]
        self.assertIn(state["feedback"], context)
        self.assertIn(state["requested_angle"], context)
        self.assertIn("Rejected choice: First subject", context)
        self.assertEqual(result["search_querries"], queries)
        self.assertEqual(result["topic_candidates"], [])
        self.assertEqual(result["feedback"], state["feedback"])

    def test_summary_and_brief_receive_feedback_and_angle(self):
        state = {**deepcopy(STATE), "selected_topic": TOPICS[0],
                 "feedback": "Explain practical limitations.", "requested_angle": "Compare alternatives"}
        with patch("app.agents.topic_summarizer._get_chain") as summary_chain, patch("builtins.print"):
            summary_chain.return_value.invoke.return_value = TopicSummary(summary="Source digest.")
            summarized = summarize_topic(state)
        inputs = summary_chain.return_value.invoke.call_args.args[0]
        self.assertEqual(inputs["feedback"], state["feedback"])
        self.assertEqual(inputs["requested_angle"], state["requested_angle"])
        with patch("app.agents.briefer.get_database") as database, patch(
            "app.agents.briefer._get_chain",
        ) as brief_chain, patch("builtins.print"):
            database.return_value.profiles.find_one.return_value = {}
            brief_chain.return_value.invoke.return_value = EditorialBrief.model_validate(BRIEF)
            result = create_brief({**state, **summarized})
        inputs = json.loads(brief_chain.return_value.invoke.call_args.args[0]["brief_input"])
        self.assertEqual(inputs["feedback"], state["feedback"])
        self.assertEqual(inputs["requested_angle"], state["requested_angle"])
        self.assertEqual(result["brief"]["provisional_angle"], BRIEF["provisional_angle"])


if __name__ == "__main__":
    unittest.main()
