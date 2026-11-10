from langgraph.graph import END


MAX_REVISIONS = 3


def review_is_current(state):
    draft = state.get("draft") or {}
    context = state.get("writer_context") or {}
    review = state.get("quality_review") or {}
    requirements = state.get("draft_requirements") or {}
    assessments = review.get("requirement_results", [])
    expected = {item["id"] for item in requirements.get("items", [])}
    return bool(draft and review.get("verdict") == "pass"
                and len(assessments) == len(expected)
                and {item["requirement_id"] for item in assessments} == expected
                and all(item["status"] == "satisfied" for item in assessments)
                and not any(item["severity"] != "minor" for item in review.get("findings", []))
                and state.get("writer_status") == "ready"
                and review.get("draft_version") == draft.get("version")
                and review.get("reviewed_text") == draft.get("text")
                and review.get("requirements_version") == requirements.get("version")
                and context.get("requirements_version") == requirements.get("version")
                and context.get("draft_version") == draft.get("version")
                and context.get("user_id") == state.get("user_id")
                and requirements.get("user_id") == state.get("user_id")
                and requirements.get("run_id") == state.get("cycle_id"))


def supervise(state):
    print(
        f"[Supervisor] user={state['user_id']} run={state['cycle_id']} "
        f"phase={state.get('autonomy_phase', 'starting')} "
        f"draft_version={(state.get('draft') or {}).get('version')} "
        f"requirements_version={(state.get('draft_requirements') or {}).get('version')} "
        f"review={(state.get('quality_review') or {}).get('verdict')} "
        f"user_decision={state.get('draft_review_decision')} "
        f"revisions={state.get('revision_count', 0)}/{MAX_REVISIONS}"
    )
    if not state.get("autonomous_active"):
        return {
            "autonomous_active": True, "autonomy_phase": "initializing",
            "draft_requirements": {"version": 0, "user_id": state["user_id"],
                                   "run_id": state["cycle_id"], "items": [], "preference_overrides": {}},
            "draft_history": [], "revision_count": 0,
            "open_draft_issues": [], "resolved_draft_issue_ids": [],
            "supervisor_action": "feedback_processor", "status": "preparing_draft_requirements",
        }
    decision = state.get("draft_review_decision")
    if decision and state.get("autonomy_phase") == "awaiting_user":
        if decision == "reject":
            return {"supervisor_action": END, "status": "draft_rejected"}
        if decision == "approve" and not state.get("awaiting_draft_clarification"):
            draft = state.get("draft") or {}
            if (review_is_current(state) and state.get("draft_review_version") == draft.get("version")
                    and state.get("draft_review_text") == draft.get("text")):
                return {"supervisor_action": "publish_linkedin", "status": "draft_approved"}
            return {"supervisor_action": END, "status": "stale_draft_approval"}
        return {"supervisor_action": "feedback_processor", "status": "processing_draft_feedback"}
    if state.get("autonomy_phase") == "feedback_processed":
        if state.get("supervisor_question"):
            return {"supervisor_action": "request_draft_clarification", "autonomy_phase": "awaiting_user"}
        return {"supervisor_action": "writer", "autonomy_phase": "writing",
                "draft_review_decision": None, "status": "writing_draft"}
    if state.get("writer_status") == "needs_material":
        return _retry(state, "Use the available supported evidence. Omit unsupported details and personal claims. "
                      "Do not request material or permission. If no useful supported post is possible, report that limitation.")
    review = state.get("quality_review") or {}
    draft = state.get("draft") or {}
    if review.get("draft_version") != draft.get("version") or not review:
        return {"supervisor_action": END, "status": "invalid_draft_review"}
    history = list(state.get("draft_history", []))
    if not history or history[-1]["draft"]["version"] != draft["version"]:
        history.append({"draft": draft, "review": review,
                        "requirements_version": state["draft_requirements"]["version"]})
    previous_issues = {_issue_key(item): item for item in state.get("open_draft_issues", [])}
    issues = [{**item, "id": previous_issues.get(_issue_key(item), item)["id"]}
              for item in review.get("findings", []) if item["severity"] != "minor"]
    current_keys = {_issue_key(item) for item in issues}
    resolved = list(dict.fromkeys(state.get("resolved_draft_issue_ids", []) + [
        item["id"] for key, item in previous_issues.items() if key not in current_keys
    ]))
    tracking = {"draft_history": history, "open_draft_issues": issues, "resolved_draft_issue_ids": resolved}
    if review_is_current(state):
        return {"supervisor_action": "send_draft_review", "autonomy_phase": "awaiting_user",
                **tracking, "status": "ready_for_user_review"}
    requirements = [item for item in review.get("requirement_results", []) if item["status"] == "unmet"]
    instructions = [f"{item['required_change']} Evidence: {item['evidence']}" for item in issues]
    instructions += [f"Resolve requirement {item['requirement_id']}: {item['evidence']}" for item in requirements]
    unchanged = len(history) > 1 and history[-2]["draft"]["text"] == draft["text"]
    if unchanged:
        return {"supervisor_action": END, "status": "draft_revision_stalled", **tracking,
                "supervisor_reason": "\n".join(instructions)}
    return {**_retry(state, "\n".join(instructions)), **tracking,
            "writer_issues": [item["id"] for item in issues]}


def _issue_key(item):
    return item["kind"], item.get("draft_span"), item["required_change"]


def _retry(state, instructions):
    print(f"[Supervisor] Revision instructions: {instructions}")
    if state.get("revision_count", 0) >= MAX_REVISIONS:
        return {"supervisor_action": END, "status": "draft_revision_limit_reached",
                "supervisor_reason": instructions}
    return {"supervisor_action": "writer", "autonomy_phase": "writing",
            "revision_count": state.get("revision_count", 0) + 1,
            "writer_feedback": instructions + "\nPreserve unaffected content. Resolve missing evidence by "
                               "using supported alternatives or omitting unsupported details; do not ask for material.",
            "draft_review_decision": None, "status": "revising_draft"}


def route_supervisor(state):
    print(
        f"[Supervisor] user={state['user_id']} run={state['cycle_id']} "
        f"next={state['supervisor_action']} status={state.get('status')} "
        f"revisions={state.get('revision_count', 0)}/{MAX_REVISIONS} "
        f"open_issues={len(state.get('open_draft_issues', []))} "
        f"resolved_issues={len(state.get('resolved_draft_issue_ids', []))}"
    )
    if state["supervisor_action"] == "request_draft_clarification":
        print(f"[Supervisor] Clarification: {state['supervisor_question']}")
    if state["supervisor_action"] == END and state.get("supervisor_reason"):
        print(f"[Supervisor] Stopped: {state['supervisor_reason']}")
    return state["supervisor_action"]
