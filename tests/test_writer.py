import json
import sys
import unittest
from copy import deepcopy
from importlib import import_module
from time import perf_counter
from unittest.mock import patch

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableLambda
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from app.autonomous.writer import write_post
from app.autonomous.writer_schema import WriterResult
from app.db.client import close_database


CLAIM = {
    "id": "claim-1", "text": "The trial involved 40 participants.", "status": "qualified",
    "evidence": [{"source_id": "source-1", "passage": "Evidence passage", "kind": "cited_finding"}],
    "qualifications": ["A single small trial; not evidence of general effectiveness."],
    "reason": "The source describes one trial.",
}

STATE = {
    "user_id": "user-1", "cycle_id": "run-1", "status": "research_incomplete",
    "brief": {
        "selected_source_id": "source-1", "content_type": "Explainer", "speaker_role": "Learner",
        "central_question": "What can this trial establish?",
        "provisional_angle": "Explain the trial's limited scope.",
        "research_questions": ["How large was the trial?"],
    },
    "sources": [{"body": "Full article body", "summary": "Source summary"}],
    "research_sources": [{"url": "https://example.org/study", "cited_findings": ["Research notes"]}],
    "claims": [CLAIM, {**CLAIM, "id": "unsupported-1", "status": "unsupported"},
               {**CLAIM, "id": "contradicted-1", "status": "contradicted"}],
    "gaps": [{"question": "Does it generalize?", "why_unresolved": "No larger study.",
              "impact": "Do not claim general effectiveness."}],
    "feedback": "Select: 5",
}



class WriterUsage(BaseCallbackHandler):
    def __init__(self):
        self.calls = []

    def on_llm_end(self, response, **kwargs):
        self.calls.extend(generation.message.usage_metadata
                          for generations in response.generations for generation in generations
                          if generation.message.usage_metadata)

    def report(self):
        inputs = sum(call["input_tokens"] for call in self.calls)
        cached = sum(call.get("input_token_details", {}).get("cache_read", 0) for call in self.calls)
        outputs = sum(call["output_tokens"] for call in self.calls)
        return {
            "api_responses": len(self.calls),
            "input_tokens": inputs,
            "cached_input_tokens": cached,
            "output_tokens_including_reasoning": outputs,
            "estimated_cost_usd": round(((inputs - cached) * 0.10 + cached * 0.01 + outputs * 0.50) / 1_000_000, 8),
            "pricing_as_of": "2026-11-02",
            "model_pricing": "https://developers.openai.com/api/docs/models/gpt-6-luna",
        }


LIVE_CONTEXT = {'user_id': '75161e42-6bda-42a0-890b-fee0c5603c64',
 'cycle_id': '407f1ead-5327-4b10-8279-1316f5454577',
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
 'instructions': ''}


LIVE_RESEARCH_RESULT = {'research_sources': [{'id': 'f061d9d7-8bda-5a35-9460-f8a7aa11e6b4',
                       'url': 'https://openai.com/index/introducing-operator/?conversion=ppt-n8n&utm_source=openai',
                       'title': 'Introducing Operator | OpenAI',
                       'retrieved_at': '2026-11-02T19:02:17.333973+00:00',
                       'origin': 'web_search',
                       'cited_findings': ['**Example 1 — Web tasks with confirmation for '
                                          'consequential actions.** OpenAI announced Operator on '
                                          '**January 23, 2025** as a **research preview**: it uses '
                                          'a browser through screenshots, clicks and typing to '
                                          'perform web tasks, can self-correct, and returns '
                                          'control to the user when it gets stuck. Its safeguards '
                                          'include confirmation before actions such as purchases '
                                          'or sending email, and refusals for certain high-risk '
                                          'tasks. The announcement establishes preview status at '
                                          'launch, not current availability; OpenAI later said '
                                          'Operator was integrated into ChatGPT agent and the '
                                          'standalone site would be sunset. '
                                          '([openai.com](https://openai.com/index/introducing-operator/?conversion=ppt-n8n&utm_source=openai))']},
                      {'id': '5891f6c4-6acf-5a7e-bf87-a3868d19f90b',
                       'url': 'https://github.com/newsroom/press-releases/coding-agent-for-github-copilot?utm_source=openai',
                       'title': 'GitHub Introduces Coding Agent For GitHub Copilot · GitHub',
                       'retrieved_at': '2026-11-02T19:02:17.334468+00:00',
                       'origin': 'web_search',
                       'cited_findings': ['**Example 2 — Delegated software work with pull-request '
                                          'review.** GitHub introduced Copilot’s asynchronous '
                                          'coding agent on **May 19, 2025**. It works in a '
                                          'development environment, pushes commits to a draft pull '
                                          'request, and can iterate on review comments. GitHub '
                                          'said the pull request requires human approval before '
                                          'CI/CD workflows run. A GitHub announcement dated **May '
                                          '13, 2025** said the agent was generally available to '
                                          'paid Copilot subscribers; access can also depend on '
                                          'organizational settings. This supports describing it as '
                                          'deployed, with human review and a specific approval '
                                          'gate—not as autonomous deployment. '
                                          '([github.com](https://github.com/newsroom/press-releases/coding-agent-for-github-copilot?utm_source=openai))']},
                      {'id': '975b6950-0fd1-56fb-a32c-907e52d6941b',
                       'url': 'https://cloud.google.com/discover/what-is-agentic-ai?utm_source=openai',
                       'title': 'What is agentic AI? Definition and differentiators | Google Cloud',
                       'retrieved_at': '2026-11-02T19:02:17.334786+00:00',
                       'origin': 'web_search',
                       'cited_findings': ['**Claim assessment — “AI agent” and “agentic AI” have '
                                          'no universally accepted distinction: Supported, with '
                                          'qualification.** The sources use different framings: '
                                          'Google Cloud describes agents as building blocks of '
                                          'agentic AI, while its separate agent guidance defines '
                                          'agentsby goal-directed action and autonomy; its legal '
                                          'terms define AI agents broadly as supervised or '
                                          'autonomous systems or workflows. This supports saying '
                                          'usage varies across sources, but the evidence reviewed '
                                          'does not establish a formal survey of all practitioners '
                                          'or standards bodies.Safer wording: **“The terms are '
                                          'used inconsistently; definitions vary by source and '
                                          'context.”** '
                                          '([cloud.google.com](https://cloud.google.com/discover/what-is-agentic-ai?utm_source=openai))']}],
 'claims': [{'id': 'operator-use-case',
             'text': 'OpenAI announced Operator on January 23, 2025, as a research preview for '
                     'browser-based web tasks. It could use screenshots, clicks, and typing, '
                     'self-correct, and return control to the user when stuck; it required '
                     'confirmation for specified consequential actions suchas purchases or sending '
                     'email. The announcement describes launch status, not current availability.',
             'status': 'supported',
             'evidence': [{'source_id': 'f061d9d7-8bda-5a35-9460-f8a7aa11e6b4',
                           'passage': '**Example 1 — Web tasks with confirmation for consequential '
                                      'actions.** OpenAI announced Operator on **January 23, '
                                      '2025** as a **research preview**: it uses a browser through '
                                      'screenshots, clicks and typing to perform web tasks, can '
                                      'self-correct, and returns control to the user when it gets '
                                      'stuck. Its safeguards include confirmation before actions '
                                      'such as purchases or sending email, and refusals forcertain '
                                      'high-risk tasks. The announcement establishes preview '
                                      'status at launch, not current availability; OpenAI later '
                                      'said Operator was integrated into ChatGPT agent and the '
                                      'standalone site would be sunset. '
                                      '([openai.com](https://openai.com/index/introducing-operator/?conversion=ppt-n8n&utm_source=openai))',
                           'kind': 'cited_finding'}],
             'qualifications': ['Research-preview status is established at launch; the cited '
                                'finding does not establish current availability.',
                                'The described safeguards apply to specified actions and do not '
                                'establish comparative safety or effectiveness.'],
             'reason': 'The cited finding documents the announcement date, capabilities, approval '
                       'points, and launch status, while explicitly limiting what can be inferred '
                       'about current availability.'},
            {'id': 'copilot-coding-agent-use-case',
             'text': 'GitHub introduced Copilot’s asynchronous coding agent on May 19, 2025. It '
                     'could work in a development environment, push commits to a draft pull '
                     'request, and iterate on review comments; human approval was required before '
                     'CI/CD workflows ran. GitHub had announced general availability to paid '
                     'Copilot subscribers on May 13, 2025.',
             'status': 'supported',
             'evidence': [{'source_id': '5891f6c4-6acf-5a7e-bf87-a3868d19f90b',
                           'passage': '**Example 2 — Delegated software work with pull-request '
                                      'review.** GitHub introduced Copilot’s asynchronous coding '
                                      'agent on **May 19, 2025**. It works in a development '
                                      'environment, pushes commits to a draft pull request, and '
                                      'can iterate on review comments. GitHub said the pull '
                                      'request requires human approval before CI/CD workflows run. '
                                      'A GitHub announcement dated **May 13, 2025** said the agent '
                                      'wasgenerally available to paid Copilot subscribers; access '
                                      'can also depend on organizational settings. This supports '
                                      'describing it as deployed,with human review and a specific '
                                      'approval gate—not as autonomous deployment. '
                                      '([github.com](https://github.com/newsroom/press-releases/coding-agent-for-github-copilot?utm_source=openai))',
                           'kind': 'cited_finding'}],
             'qualifications': ['Access may depend on organizational settings.',
                                'The cited approval gate does not support describing the agent as '
                                'autonomously deploying changes.'],
             'reason': 'The cited finding states the introduction and availability dates, '
                       'described workflow, and human approval point.'},
            {'id': 'terminology-distinction',
             'text': 'The terms “AI agent” and “agentic AI” are used inconsistently; definitions '
                     'vary by source and context.',
             'status': 'qualified',
             'evidence': [{'source_id': '975b6950-0fd1-56fb-a32c-907e52d6941b',
                           'passage': '**Claim assessment — “AI agent” and “agentic AI” have no '
                                      'universally accepted distinction: Supported, with '
                                      'qualification.** The sources use different framings: Google '
                                      'Cloud describes agents as building blocks of agentic AI, '
                                      'while its separate agent guidance defines agents by '
                                      'goal-directed action and autonomy; its legal terms define '
                                      'AI agents broadly as supervised or autonomous systems or '
                                      'workflows. This supports saying usage varies across '
                                      'sources, but the evidence reviewed does not establish a '
                                      'formal survey of all practitioners or standards bodies. '
                                      'Safer wording: **“The terms are used inconsistently; '
                                      'definitions vary by source and context.”** '
                                      '([cloud.google.com](https://cloud.google.com/discover/what-is-agentic-ai?utm_source=openai))',
                           'kind': 'cited_finding'}],
             'qualifications': ['This supports variation across the sources reviewed, not a formal '
                                'survey of all practitioners or standards bodies.'],
             'reason': 'The cited finding supports inconsistent usage across sources but '
                       'explicitly limits the scope of that conclusion.'}],
 'gaps': [{'question': 'What is the minimum agentic capability set sufficient for a given use '
                       'case, and do the two examples establish that one design is better than '
                       'another?',
           'why_unresolved': 'The sources document product behavior, approval points, and stated '
                             'launch status, but the notes identify no independent evaluations '
                             'establishing minimum sufficiency or comparative effectiveness, '
                             'safety, or cost.',
           'impact': 'The post can use the cases to illustrate different oversight designs and '
                     'offer them as examples, but cannot present either as proven minimum '
                     'sufficient or claim one approach performs better.'}]}




def live_state():
    return {**deepcopy(LIVE_CONTEXT), **deepcopy(LIVE_RESEARCH_RESULT)}


def run_live():
    writer = import_module("app.autonomous.writer")
    usage = WriterUsage()
    chain = writer._get_chain().with_config({"callbacks": [usage]})
    state = live_state()
    print("Running only the real writer with the saved brief, research result, and profile preferences.")

    def invoke_with_inputs(inputs):
        print("\nWriter system prompt:\n" + writer.SYSTEM_PROMPT)
        print("\nWriter model inputs:", json.dumps(
            json.loads(inputs["writer_input"]), ensure_ascii=False, indent=2,
        ))
        return chain.invoke(inputs)

    started = perf_counter()
    try:
        with patch("app.autonomous.writer._get_chain", return_value=RunnableLambda(invoke_with_inputs)):
            output = write_post(state)
        if output.get("draft"):
            print("\nPublic post:\n" + output["draft"]["text"])
        else:
            print("Writer work request:", json.dumps(output, ensure_ascii=False, indent=2))
        return output
    finally:
        report = {**usage.report(), "elapsed_seconds": round(perf_counter() - started, 2)}
        print("Writer usage and estimated cost:", json.dumps(report, indent=2))
        close_database()


WRITER_STATE = {
    **deepcopy(STATE),
    "research_sources": [{"id": "source-1", "title": "Trial", "url": "https://example.org/trial",
                          "cited_findings": ["Private research notes"]}],
}
RESULT = {
    "text": "The trial involved 40 participants. A single small trial cannot establish general effectiveness.",
    "evidence_map": [{
        "draft_span": "The trial involved 40 participants.",
        "claim_ids": ["claim-1"], "personal_material_ids": [],
    }],
    "work_request": None,
}


class WriterTests(unittest.TestCase):
    def test_live_fixture_uses_brief_and_research_directly(self):
        state = live_state()
        original = deepcopy(state)
        result = deepcopy(RESULT)
        result["evidence_map"][0]["claim_ids"] = ["operator-use-case"]
        output, inputs, _ = self.run_writer(state=state, result=result)
        self.assertEqual(inputs["brief"]["central_question"], state["brief"]["central_question"])
        self.assertEqual(inputs["research_gaps"], state["gaps"])
        self.assertNotIn("outline", inputs)
        self.assertEqual({item["id"] for item in inputs["usable_claims"]}, {
            "operator-use-case", "copilot-coding-agent-use-case", "terminology-distinction",
        })
        self.assertEqual(len(inputs["citation_sources"]), 3)
        self.assertNotIn("outline_version", output["draft"])
        self.assertEqual(inputs["writing_samples"], [])
        self.assertEqual(state, original)

    def test_live_runner_invokes_only_writer_and_attaches_usage_callback(self):
        with patch("app.autonomous.writer._get_chain") as factory, patch(
            "app.autonomous.writer.get_database",
        ) as database, patch("tests.test_writer.close_database") as close, patch(
            "app.autonomous.researcher.research",
        ) as researcher, patch("builtins.print"):
            database.return_value.profiles.find_one.return_value = {}
            chain = factory.return_value.with_config.return_value
            result = {**deepcopy(RESULT), "evidence_map": []}
            chain.invoke.return_value = WriterResult.model_validate(result)
            output = run_live()
        self.assertEqual(output["writer_status"], "ready")
        chain.invoke.assert_called_once()
        self.assertEqual(len(factory.return_value.with_config.call_args.args[0]["callbacks"]), 1)
        researcher.assert_not_called()
        close.assert_called_once()

    def run_writer(self, state=None, profile=None, result=None):
        with patch("app.autonomous.writer.get_database") as database, patch(
            "app.autonomous.writer._get_chain",
        ) as chain, patch("builtins.print"):
            database.return_value.profiles.find_one.return_value = profile or {}
            chain.return_value.invoke.return_value = WriterResult.model_validate(result or RESULT)
            output = write_post(deepcopy(WRITER_STATE) if state is None else state)
        inputs = (json.loads(chain.return_value.invoke.call_args.args[0]["writer_input"])
                  if chain.return_value.invoke.called else None)
        return output, inputs, database.return_value.profiles.find_one.call_args

    def test_compact_input_without_samples_or_bodies(self):
        profile = {
            "preferences": {"tone": ["Thoughtful"], "post_length": "Custom", "word_range": "100-200",
                            "paragraph_style": "Mixed lengths", "imperfection_injection": True},
            "writing_samples": {"items": [{"text": "PRIVATE SAMPLE"}]},
            "audience": {"target_audience": ["Teachers"], "audience_level": "Beginner"},
        }
        state = deepcopy(WRITER_STATE)
        state["selected_topic"] = {"id": "source-1", "title": "Risks and mitigation of AI agents"}
        state["voice"] = {"tone": ["Direct"], "voice_instructions": "Use plain language."}
        state["summary"] = "Frame learning in progress honestly; use measured explanations."
        state["outline_preferences"] = {"preferred_organisation": ["Claim to evidence"]}
        state["openings"] = {"preferred_opening": ["Question"]}
        state["endings"] = {"closing_style": ["Practical takeaway"]}
        original = deepcopy(state)
        output, inputs, query = self.run_writer(state, profile)
        self.assertEqual(inputs["selected_topic"], state["selected_topic"])
        self.assertEqual(inputs["writing_preferences"]["tone"], ["Direct"])
        self.assertEqual(inputs["writing_preferences"]["word_range"], "100-200")
        self.assertEqual(inputs["writing_preferences"]["paragraph_style"], "Mixed lengths")
        self.assertEqual(inputs["writing_preferences"]["preferred_organisation"], ["Claim to evidence"])
        self.assertEqual(inputs["writing_preferences"]["preferred_opening"], ["Question"])
        self.assertEqual(inputs["writing_preferences"]["closing_style"], ["Practical takeaway"])
        self.assertEqual(set(inputs["brief"]), {
            "content_type", "speaker_role", "central_question", "provisional_angle", "research_questions",
        })
        self.assertEqual(inputs["usable_claims"][0]["qualifications"], CLAIM["qualifications"])
        self.assertEqual(inputs["usable_claims"][0]["source_ids"], ["source-1"])
        self.assertEqual(inputs["usable_claims"][0]["evidence"], CLAIM["evidence"])
        self.assertEqual(inputs["supporting_sources"], [{
            "id": "source-1", "title": "Trial", "cited_findings": ["Private research notes"],
        }])
        self.assertNotIn("profile_summary", inputs)
        self.assertNotIn(state["summary"], json.dumps(inputs))
        self.assertNotIn("profile_summary", output["writer_context"])
        self.assertEqual(inputs["citation_sources"], [{"id": "source-1", "title": "Trial"}])
        self.assertNotIn("https://example.org/trial", json.dumps(inputs))
        for value in ("PRIVATE SAMPLE", "Full article body",
                      "imperfection_injection", "unsupported-1", "contradicted-1"):
            self.assertNotIn(value, json.dumps(inputs))
        self.assertIn("writing_samples", query.args[1])
        self.assertEqual(output["draft"]["version"], 1)
        self.assertIsNone(output["draft"]["parent_version"])
        self.assertNotIn("outline_version", output["draft"])
        self.assertIsNone(output["writer_work_request"])
        self.assertEqual(inputs["research_gaps"], state["gaps"])
        self.assertEqual(output["writer_status"], "ready")
        self.assertEqual(state, original)

    def test_all_usable_claims_are_sent_without_outline_selection(self):
        state = deepcopy(WRITER_STATE)
        state["claims"].append({**CLAIM, "id": "unused-claim"})
        _, inputs, _ = self.run_writer(state)
        self.assertEqual([claim["id"] for claim in inputs["usable_claims"]], ["claim-1", "unused-claim"])

    def test_missing_evidence_does_not_call_model(self):
        for update in (
            {"claims": []}, {"research_sources": []},
        ):
            with self.subTest(update=update):
                output, inputs, _ = self.run_writer({**deepcopy(WRITER_STATE), **update})
                self.assertEqual(output["writer_status"], "needs_material")
                self.assertNotIn("draft", output)
                self.assertIsNone(inputs)

    def test_personal_permissions_are_rechecked_and_details_filtered(self):
        state = deepcopy(WRITER_STATE)
        state["writer_personal_material_ids"] = ["experience-1"]
        experience = {
            "id": "experience-1", "usage_permission": "May use in drafts",
            "permitted_details": ["Role"], "personal_role": "Teacher",
            "outcome": "SECRET OUTCOME", "situation": "SECRET SITUATION",
            "anonymisation": "Do not name the school.",
        }
        profile = {"experiences": {"items": [experience]}}
        result = deepcopy(RESULT)
        result["evidence_map"][0]["personal_material_ids"] = ["experience-1"]
        _, inputs, _ = self.run_writer(state, profile, result)
        self.assertEqual(inputs["personal_material"][0]["personal_role"], "Teacher")
        self.assertIn("Do not name the school.", json.dumps(inputs))
        self.assertNotIn("SECRET", json.dumps(inputs))
        experience["usage_permission"] = "Ask before using"
        output, inputs, _ = self.run_writer(state, profile)
        self.assertEqual(output["writer_status"], "needs_material")
        self.assertIsNone(inputs)

    def test_unknown_output_references_are_rejected(self):
        for key in ("claim_ids", "personal_material_ids"):
            result = deepcopy(RESULT)
            result["evidence_map"][0][key] = ["invented"]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_writer(result=result)

    def test_revision_versions_and_context(self):
        state = deepcopy(WRITER_STATE)
        state.update({"draft": {**deepcopy(RESULT), "version": 3},
                      "writer_feedback": "Simplify the opening.", "writer_issues": ["Too formal"],
                      "instructions": "Write for teachers."})
        original = deepcopy(state)
        output, inputs, _ = self.run_writer(state)
        self.assertEqual(inputs["previous_draft"], RESULT["text"])
        self.assertEqual(inputs["assigned_issues"], ["Too formal"])
        self.assertEqual(inputs["current_instructions"], "Write for teachers.")
        self.assertEqual(output["draft"]["version"], 4)
        self.assertEqual(output["draft"]["parent_version"], 3)
        self.assertEqual(state, original)

    def test_work_request_preserves_existing_draft(self):
        state = {**deepcopy(WRITER_STATE), "draft": {"text": "Existing post", "version": 2}}
        result = {"text": None, "evidence_map": [], "work_request": {
            "question": "Which result may be shared?", "why_needed": "The essential result is absent.",
        }}
        output, _, _ = self.run_writer(state, result=result)
        self.assertEqual(output["writer_status"], "needs_material")
        self.assertEqual(output["writer_work_request"], result["work_request"])
        self.assertNotIn("draft", output)
        self.assertEqual(state["draft"]["version"], 2)

    def test_strict_schema_and_exact_spans(self):
        schema = to_strict_json_schema(WriterResult)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), {"text", "evidence_map", "work_request"})
        for changes in ({"version": 1}, {"text": None}, {"text": " "},
                        {"work_request": {"question": "Why?", "why_needed": "Missing"}}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                WriterResult.model_validate({**RESULT, **changes})
        result = deepcopy(RESULT)
        result["evidence_map"][0]["draft_span"] = "A span absent from the post"
        with self.assertRaises(ValidationError):
            WriterResult.model_validate(result)

    def test_no_brief_does_not_call_model_or_database(self):
        with patch("app.autonomous.writer._get_chain") as chain, patch(
            "app.autonomous.writer.get_database",
        ) as database:
            self.assertEqual(write_post({}), {})
            chain.assert_not_called()
            database.assert_not_called()


if __name__ == "__main__":
    if "--live" in sys.argv:
        run_live()
    else:
        unittest.main()
