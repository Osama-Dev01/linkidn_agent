import json
import sys
from time import perf_counter
from pathlib import Path

from dotenv import load_dotenv
import unittest
from copy import deepcopy
from importlib import import_module
from types import SimpleNamespace as Item
from unittest.mock import MagicMock, patch

from openai import OpenAI
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from app.autonomous.research_schema import Claim, ResearchLedger, ResearchPreferences, ResearchResult
from app.autonomous.research_tools import cited_sources
from app.autonomous.researcher import research
from app.db.client import close_database, get_database
from app.support_funcs.load_preferences import load_preferences


LOCAL_SOURCE = {
    "id": "local-1", "url": "https://example.org/study", "title": "Study",
    "body": "The trial involved 40 participants in 2025.", "summary": "A small trial.",
    "content_type": "web_page", "published_at": "2025-06-01",
}
FINDING = "The 2025 trial involved 40 participants. [Study]"
STATE = {
    "user_id": "user-1", "cycle_id": "run-1", "sources": [LOCAL_SOURCE],
    "brief_status": "ready_for_research",
    "brief": {
        "selected_source_id": "local-1", "central_question": "What did the trial show?",
        "provisional_angle": "Explain the trial's scope",
        "research_questions": ["How many participants were included?"],
    },
}


def web_response(url="https://example.org/study", text=FINDING):
    citation = Item(type="url_citation", url=url, title="Study", start_index=0, end_index=len(text))
    return Item(status="completed", output_text=text, output=[
        Item(type="web_search_call", action=Item(type="search")),
        Item(type="message", content=[Item(type="output_text", text=text, annotations=[citation])]),
    ])


def claim(source_id, passage=FINDING, kind="cited_finding"):
    return {
        "id": "claim-1", "text": "The trial involved 40 participants.", "status": "qualified",
        "evidence": [{"source_id": source_id, "passage": passage, "kind": kind}],
        "qualifications": ["One trial in 2025; no broader population conclusion."],
        "reason": "The cited finding describes only this trial.",
    }


WEB_SOURCE = cited_sources(web_response(), "user-1", "run-1", [])[0]
WEB_CLAIM = claim(WEB_SOURCE.id)


class ResearchValidationTests(unittest.TestCase):
    def test_live_cost_counts_tokens_and_search_actions(self):
        response = web_response()
        response.usage = Item(input_tokens=20000, input_tokens_details=Item(cached_tokens=0),
                              output_tokens=4000)
        response.output.extend([
            Item(type="web_search_call", action=Item(type="open_page")),
            Item(type="web_search_call", action=Item(type="search")),
        ])
        usage = live_usage([response])
        self.assertEqual(usage["web_searches"], 2)
        self.assertEqual(usage["hosted_web_calls"], 3)
        self.assertAlmostEqual(usage["estimated_cost_usd"], 0.024)
        response.usage.input_tokens_details.cached_tokens = 10000
        self.assertAlmostEqual(live_usage([response])["estimated_cost_usd"], 0.0231)

    def test_ledger_uses_strict_schema(self):
        schema = to_strict_json_schema(ResearchLedger)
        self.assertFalse(schema["additionalProperties"])
        for definition in schema["$defs"].values():
            self.assertFalse(definition["additionalProperties"])
            self.assertEqual(set(definition["required"]), set(definition["properties"]))
        with self.assertRaises(ValidationError):
            ResearchPreferences(minimum_sources="2")

    def test_claim_status_and_qualifications(self):
        for changes in (
            {"status": "verified"}, {"evidence": []}, {"qualifications": []},
            {"reason": " "}, {"extra": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                Claim.model_validate({**WEB_CLAIM, **changes})
        Claim.model_validate({**WEB_CLAIM, "status": "unsupported", "evidence": [], "qualifications": []})
        with self.assertRaises(ValidationError):
            ResearchLedger(claims=[WEB_CLAIM, WEB_CLAIM], gaps=[])

    def test_evidence_must_match_actual_citations_and_cannot_claim_verified_quotes(self):
        ResearchResult(sources=[WEB_SOURCE], claims=[WEB_CLAIM], gaps=[])
        for evidence in (
            {"source_id": "invented", "passage": FINDING, "kind": "cited_finding"},
            {"source_id": WEB_SOURCE.id, "passage": "Invented result", "kind": "cited_finding"},
            {"source_id": WEB_SOURCE.id, "passage": FINDING, "kind": "source_quote"},
        ):
            with self.subTest(evidence=evidence), self.assertRaises(ValidationError):
                ResearchResult(sources=[WEB_SOURCE], claims=[{**WEB_CLAIM, "evidence": [evidence]}], gaps=[])


class SourceTests(unittest.TestCase):
    def test_citation_ids_are_stable_and_blocked_sources_are_excluded(self):
        repeated = cited_sources(web_response("https://example.org/study#results"), "user-1", "run-1", [])
        self.assertEqual(repeated[0].id, WEB_SOURCE.id)
        self.assertEqual(cited_sources(web_response(), "user-1", "run-1", ["example.org"]), [])
        self.assertNotIn("body", WEB_SOURCE.model_dump())
        response = web_response()
        response.output[1].content[0].annotations[0].end_index = 9999
        with self.assertRaises(ValueError):
            cited_sources(response, "user-1", "run-1", [])



class ResearchAgentTests(unittest.TestCase):
    def run_research(self, responses=None, claims=None, profile=None, state=None, ledger_responses=None):
        client = MagicMock()
        client.responses.create.side_effect = responses or [web_response()]
        client.responses.parse.return_value = Item(
            status="completed", output_parsed=ResearchLedger(claims=claims if claims is not None else [WEB_CLAIM], gaps=[]),
        )
        client.responses.parse.side_effect = ledger_responses
        with patch("app.autonomous.researcher.get_database") as database, patch(
            "app.autonomous.researcher.OpenAI", return_value=client,
        ), patch("builtins.print"):
            database.return_value.profiles.find_one.return_value = profile or {}
            result = research(deepcopy(state or STATE))
        return result, client

    def test_gpt6_web_research_and_strict_ledger_without_web_bodies(self):
        result, client = self.run_research()
        request = client.responses.create.call_args.kwargs
        self.assertEqual(request["model"], "gpt-6-luna")
        self.assertEqual(request["max_tool_calls"], 2)
        self.assertEqual([tool["type"] for tool in request["tools"]], ["web_search"])
        initial = request["input"][0]["content"]
        self.assertNotIn(LOCAL_SOURCE["body"], initial)
        self.assertIn(LOCAL_SOURCE["summary"], initial)
        final_request = client.responses.parse.call_args.kwargs
        self.assertEqual(final_request["model"], "gpt-6-luna")
        self.assertIs(final_request["text_format"], ResearchLedger)
        self.assertNotIn("tools", final_request)
        self.assertNotIn(LOCAL_SOURCE["body"], final_request["input"])
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(result["status"], "research_complete")
        self.assertEqual(result["claims"][0]["evidence"][0]["kind"], "cited_finding")
        self.assertNotIn("body", result["research_sources"][0])

    def test_minimum_sources_becomes_a_gap(self):
        result, _ = self.run_research(profile={"preferences": {"minimum_sources": 2}})
        self.assertEqual(result["status"], "research_incomplete")
        self.assertIn("2 required", result["gaps"][0]["why_unresolved"])

    def test_invalid_qualified_claim_is_repaired_without_repeating_research(self):
        with self.assertRaises(ValidationError) as invalid:
            ResearchLedger(claims=[{**WEB_CLAIM, "qualifications": []}], gaps=[])
        repaired = Item(status="completed", output_parsed=ResearchLedger(claims=[WEB_CLAIM], gaps=[]))
        result, client = self.run_research(ledger_responses=[invalid.exception, repaired])
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(client.responses.parse.call_count, 2)
        original, retry = [json.loads(call.kwargs["input"]) for call in client.responses.parse.call_args_list]
        for key in ("assignment", "research_notes", "sources"):
            self.assertEqual(retry[key], original[key])
        self.assertIn("Qualified claims require qualifications", retry["validation_errors"][0]["msg"])
        self.assertEqual(result["claims"][0]["qualifications"], WEB_CLAIM["qualifications"])

    def test_repeated_validation_failure_stops_after_one_repair(self):
        with self.assertRaises(ValidationError) as invalid:
            ResearchLedger(claims=[{**WEB_CLAIM, "qualifications": []}], gaps=[])
        with patch("app.autonomous.researcher.OpenAI") as factory, patch(
            "app.autonomous.researcher.get_database",
        ) as database, patch("builtins.print"):
            database.return_value.profiles.find_one.return_value = {}
            client = factory.return_value
            client.responses.create.return_value = web_response()
            client.responses.parse.side_effect = [invalid.exception, invalid.exception]
            with self.assertRaises(ValidationError):
                research(deepcopy(STATE))
        self.assertEqual(client.responses.create.call_count, 1)
        self.assertEqual(client.responses.parse.call_count, 2)

    def test_repair_still_rejects_fabricated_evidence(self):
        with self.assertRaises(ValidationError) as invalid:
            ResearchLedger(claims=[{**WEB_CLAIM, "qualifications": []}], gaps=[])
        fabricated = Item(status="completed", output_parsed=ResearchLedger(
            claims=[claim(WEB_SOURCE.id, passage="Invented result")], gaps=[],
        ))
        with self.assertRaisesRegex(ValidationError, "Evidence must occur"):
            self.run_research(ledger_responses=[invalid.exception, fabricated])

    def test_research_input_omits_duplicate_context_and_time_preferences(self):
        state = {
            **STATE, "instructions": "General instructions", "feedback": "Select: 5",
            "selected_topic": {"id": "source-1", "title": "Risks and mitigation of AI agents"},
            "research_objective": "Overridden research question?",
            "topic_interests": {"freshness": "Timely", "recency_window": 7},
            "voice": {"technical_depth": "Deeply technical"},
        }
        profile = {
            "audience": {"audience_level": "Advanced"},
            "interests": {"freshness": "Balanced", "recency_window": 30},
            "preferences": {"preferred_evidence": ["Official documentation"]},
        }
        _, client = self.run_research(state=state, profile=profile)
        inputs = json.loads(client.responses.create.call_args.kwargs["input"][0]["content"])
        self.assertEqual(set(inputs), {"selected_topic", "brief", "selected_source", "research_requirements", "today"})
        self.assertEqual(inputs["selected_topic"], state["selected_topic"])
        self.assertEqual(inputs["brief"]["central_question"], "Overridden research question?")
        self.assertEqual(inputs["selected_source"], {
            key: LOCAL_SOURCE[key] for key in ("title", "url", "summary")
        })
        self.assertEqual(inputs["research_requirements"], {
            "preferred_evidence": ["Official documentation"], "minimum_sources": 1,
        })
        self.assertNotIn("freshness", client.responses.parse.call_args.kwargs["input"])
        self.assertNotIn("recency_window", client.responses.parse.call_args.kwargs["input"])

    def test_existing_claims_are_included_only_when_supplied(self):
        _, client = self.run_research(state={**STATE, "claims": [WEB_CLAIM]})
        inputs = json.loads(client.responses.create.call_args.kwargs["input"][0]["content"])
        self.assertEqual(inputs["existing_claims"], [WEB_CLAIM])

    def test_no_actual_citation_rejects_evidence(self):
        response = web_response()
        response.output[1].content[0].annotations = []
        with self.assertRaises(ValidationError):
            self.run_research(responses=[response])



    def test_blocked_domains_and_depth_are_passed_to_provider(self):
        state = {**STATE, "research_preferences": {"research_depth": "Deep research", "distrusted_sources": ["https://blocked.org"]}}
        _, client = self.run_research(state=state)
        request = client.responses.create.call_args.kwargs
        self.assertEqual(request["max_tool_calls"], 3)
        self.assertEqual(request["tools"][0]["filters"], {"blocked_domains": ["blocked.org"]})

    def test_incomplete_response_is_not_used(self):
        response = web_response()
        response.status = "incomplete"
        with self.assertRaises(ValueError):
            self.run_research(responses=[response])

    def test_missing_brief_does_not_call_openai(self):
        with patch("app.autonomous.researcher.OpenAI") as client:
            self.assertEqual(research({}), {})
            self.assertEqual(research({**STATE, "brief_status": "needs_source"}), {})
            client.assert_not_called()

    def test_graph_connects_briefer_to_researcher(self):
        from langgraph.checkpoint.memory import InMemorySaver

        with patch("app.db.client.get_checkpointer", return_value=InMemorySaver()):
            graph = import_module("app.graph.builder").graph.get_graph()
        edges = {(edge.source, edge.target) for edge in graph.edges}
        self.assertIn(("create_brief", "researcher"), edges)
        self.assertIn(("researcher", "supervisor"), edges)
        self.assertNotIn("outliner", graph.nodes)
        self.assertIn(("supervisor", "writer"), edges)
        self.assertIn(("writer", "quality_review"), edges)
        self.assertIn(("quality_review", "supervisor"), edges)
        self.assertIn(("supervisor", "send_draft_review"), edges)
        self.assertIn(("send_draft_review", "receive_draft_review"), edges)
        self.assertIn(("receive_draft_review", "supervisor"), edges)
        self.assertIn(("feedback_processor", "supervisor"), edges)
        self.assertIn("quality_review", graph.nodes)
        self.assertNotIn(("create_brief", "__end__"), edges)


LIVE_STATE = {'user_id': '75161e42-6bda-42a0-890b-fee0c5603c64',
 'cycle_id': '407f1ead-5327-4b10-8279-1316f5454577',
 'instructions': '',
 'selected_topic': {'id': 'ad1cdf38-3242-562c-89e7-a8e75a515c7f',
                    'title': 'AI Agents vs. Agentic AI: A PM’s Guide to the Distinction That '
                             'Actually Matters'},
 'sources': [{'title': 'AI Agents vs. Agentic AI: A PM’s Guide to the Distinction That Actually '
                       'Matters',
              'description': '“Agentic AI” is a property. It describes how a system behaves: '
                             'goal-directed, multi-step, capable of taking action in the world '
                             'without a human approving every move. “AI agent” is a thing. A '
                             'discrete software system, intentionally designed and scoped, that '
                             'expresses agentic behavior. [...] > “Agentic AI describes a property '
                             'of AI behavior: how goal-directed, multi-step, and autonomous a '
                             'system is. It’s a spectrum, not a category. AI agents are systems '
                             'deliberately architected to sit at the higher end of that spectrum, '
                             'combining tool use, planning, memory, and self-correction into a '
                             'persistent loop. As a PM, I think about agenticism across five '
                             'dimensions, and the product question I always ask is: how far along '
                             'each dimension does this use case actually need to go? Because each '
                             '[...] The relationship is definitional. An AI agent is an '
                             'implementation that sits at the higher end of the agentic spectrum. '
                             'But not everythingthat exhibits agentic behavior is a fully '
                             'architected AI agent, and not everything called an “AI agent” is '
                             'actually very agentic.',
              'matched_topics': [],
              'matched_queries': ['Agentic AI'],
              'url': 'https://aipmguru.substack.com/p/ai-agents-vs-agentic-ai-a-pms-guide',
              'source': 'substack',
              'retrieved_at': '2026-11-02T17:31:22.783387+00:00',
              'published_at': None,
              'id': 'ad1cdf38-3242-562c-89e7-a8e75a515c7f',
              'extracted_source': 'substack',
              'summary': '**Source context and main argument**  \n'
                         'The source is an article titled "AI Agents vs. Agentic AI: A PM’s Guide '
                         'to the Distinction That Actually Matters" by Shaili Guru. The central '
                         'thesis is to clarify the distinction between "AI agents" and "agentic '
                         'AI" in a practical context for product management (PM). The article '
                         'argues that conflating these terms can lead to incorrect scoping of AI '
                         'projects, resulting in either over-engineering or under-engineering '
                         'solutions. The author emphasizes the need for a framework that helps PMs '
                         'make informed decisions about the level of agentic behavior required for '
                         'specific use cases.  \n'
                         '\n'
                         '**Key concepts and mechanisms**  \n'
                         '- **Agentic AI**: A property that describes how a system behaves in a '
                         'goal-directed, multi-step manner, capable of taking actions without '
                         'human approval. It exists on a spectrum.  \n'
                         '- **AI Agent**: A discrete software system designed to exhibit agentic '
                         'behavior, positioned at the higher end of the agentic spectrum.  \n'
                         '- **Agentic Spectrum**: Defined by five dimensions that characterize the '
                         'level of agentic behavior in AI systems:  \n'
                         '  1. **Tool Use**: The ability of a model to perform actions using '
                         'external tools (e.g., APIs, databases).  \n'
                         '  2. **Planning and Sequential Reasoning**: The ability to decompose '
                         'goals into subtasks and execute them in order, using mechanisms like the '
                         'ReAct pattern.  \n'
                         '  3. **Memory**: The capacity to retain information across interactions, '
                         'categorized into four types: in-context, external, semantic, and '
                         'episodic memory.  \n'
                         '  4. **Self-Correction**: The ability of a system to evaluate its '
                         'outputs and improve them through feedback loops.  \n'
                         '  5. **Human-in-the-Loop (HITL) Reduction**: The degree to which human '
                         'oversight is minimized in the decision-making process.  \n'
                         '\n'
                         '**Evidence and concrete details**  \n'
                         '- The article notes that a chatbot with a single web search tool is '
                         'considered "mildly agentic" due to its limited autonomy, while a system '
                         'like Devin, which can run tests and fix errors autonomously, is '
                         'described as "deeply agentic."  \n'
                         '- The ReAct pattern, introduced in a 2022 Google Research/Princeton '
                         'paper, combines reasoning and action, allowing for planning in AI '
                         'systems.  \n'
                         '- The five dimensions of agentic behavior are critical for PMs to '
                         'understand when scoping AI products, as each dimension adds complexity '
                         'andpotential failure modes.  \n'
                         '\n'
                         '**Use cases, examples, and comparisons**  \n'
                         '- **Example of a chatbot**: A simple RAG (Retrieve, Answer, Generate) '
                         'chatbot has limited agentic capabilities (one dial turned up).  \n'
                         '- **Example of Devin**: A sophisticated AI agent that utilizes all five '
                         'dimensions, demonstrating a significant gap in complexity and capability '
                         'compared to simpler systems.  \n'
                         '- **Comparison of HITL**: A system that drafts an email for review is '
                         'mildly agentic, while one that autonomously sends emails after '
                         'evaluating confidence is more agentic.  \n'
                         '\n'
                         '**Trade-offs, conclusions, and future directions**  \n'
                         '- The article concludes that not all products require full agentic '
                         'capabilities; many only need two or three dimensions.  \n'
                         '- The principle of using the smallest capability that works is '
                         'emphasized, as more agentic systems introduce greater complexity, '
                         'latency variance, and privacy obligations.  \n'
                         '- PMs should ask how agentic a system needs to be based on specific '
                         'requirements, balancing the need for functionality against the risks '
                         'andcomplexities involved.  \n'
                         '\n'
                         '**Limitations and missing information**  \n'
                         '- The article does not provide specific case studies or quantitative '
                         'metrics to illustrate the effectiveness of different levels of agentic '
                         'behavior.  \n'
                         '- There are no specified dates for the introduction of the ReAct pattern '
                         'or other frameworks mentioned, nor are there details on the '
                         'broaderimplications of these distinctions in various industries.'}],
 'brief': {'selected_source_id': 'ad1cdf38-3242-562c-89e7-a8e75a515c7f',
           'content_type': 'Tutorial',
           'speaker_role': 'Learner',
           'central_question': 'How can teams choose the minimum agentic capabilities a use case '
                               'needs?',
           'provisional_angle': 'Compare two concrete use cases to explain why different tasks '
                                'need different levels of autonomy.',
           'research_questions': ['Find two recent, documented use cases with different levels of '
                                  'autonomy. For each, identify the task, demonstrated '
                                  'capabilities, human approval points, announcement date, and '
                                  'deployment status.']},
 'brief_status': 'ready_for_research',
 'feedback': '5\nFeedback : also metion latest use cases that are emerging now for both',
 'claims': [],
 'gaps': [],
 'status': 'topic_selected'}



def live_usage(responses):
    input_tokens = sum(response.usage.input_tokens for response in responses if response.usage)
    cached_tokens = sum(response.usage.input_tokens_details.cached_tokens
                        for response in responses if response.usage)
    output_tokens = sum(response.usage.output_tokens for response in responses if response.usage)
    web_calls = [item for response in responses for item in response.output
                 if item.type == "web_search_call"]
    searches = sum(item.action.type == "search" for item in web_calls)
    token_cost = ((input_tokens - cached_tokens) * 0.10 + cached_tokens * 0.01
                  + output_tokens * 0.50) / 1_000_000
    return {
        "api_responses": len(responses),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens_including_reasoning": output_tokens,
        "hosted_web_calls": len(web_calls),
        "web_searches": searches,
        "estimated_token_cost_usd": round(token_cost, 8),
        "estimated_search_cost_usd": round(searches * 0.01, 8),
        "estimated_cost_usd": round(token_cost + searches * 0.01, 8),
        "pricing_as_of": "2026-11-02",
        "model_pricing": "https://developers.openai.com/api/docs/models/gpt-6-luna",
        "search_pricing": "https://developers.openai.com/api/docs/pricing",
    }


def run_live():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    profile = get_database().profiles.find_one({"user_id": LIVE_STATE["user_id"]}, {"_id": 0}) or {}
    state = {**load_preferences(profile)["preferences"], **deepcopy(LIVE_STATE)}
    responses = []
    clients = []

    def measured_client(**kwargs):
        client = OpenAI(**kwargs)
        clients.append(client)

        def measured(method, name):
            def invoke(*args, **params):
                response = method(*args, **params)
                responses.append(response)
                if name == "create" and response.output_text:
                    print("Research notes:", response.output_text)
                return response
            return invoke

        client.responses.create = measured(client.responses.create, "create")
        client.responses.parse = measured(client.responses.parse, "parse")
        return client

    print("Running the real researcher with the pasted brief and saved profile preferences.")
    print("Research depth:", state.get("research_preferences", {}).get("research_depth", "Standard"))
    started = perf_counter()
    try:
        with patch("app.autonomous.researcher.OpenAI", side_effect=measured_client):
            return research(state)
    finally:
        report = {**live_usage(responses), "elapsed_seconds": round(perf_counter() - started, 2)}
        print("Researcher usage and estimated cost:", json.dumps(report, indent=2))
        for client in clients:
            client.close()
        close_database()


if __name__ == "__main__":
    if "--live" in sys.argv:
        run_live()
    else:
        unittest.main()
