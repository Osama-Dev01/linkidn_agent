from uuid import uuid4

from langgraph.types import Command

from app.graph.state import ResearchState
from app.services.send_mail import wait_for_reply, wait_for_draft_reply
from app.support_funcs.load_preferences import load_preferences
from app.db.client import get_database
from app.services.preference_learning import PREFERENCE_GROUPS


def run_engine_task(profile: dict) -> ResearchState:
    try:
        return run_engine(profile)
    finally:
        get_database().engine_runs.delete_one({"_id": profile["user_id"]})


def run_engine(profile: dict) -> ResearchState:
    collection = get_database().preferences
    preferences = collection.find_one({"user_id": profile["user_id"]}, {"_id": 0, "user_id": 0})
    if preferences is None:
        mapped = load_preferences(profile)["preferences"]
        preferences = {group: mapped.get(group, {}) for group in PREFERENCE_GROUPS}
        collection.replace_one(
            {"user_id": profile["user_id"]},
            {"user_id": profile["user_id"], **preferences},
            upsert=True,
        )
    return run_graph(profile["user_id"], preferences)


def run_graph(user_id: str, preferences: dict) -> ResearchState:
    from app.graph.builder import graph

    initial_state: ResearchState = {
        "user_id": user_id,
        "cycle_id": str(uuid4()),
        "instructions": "",
        "topic_interests": preferences.get("topic_interests", {}),
        "selection_taste": preferences.get("selection_taste", {}),
        "content_types": preferences.get("content_types", {}),
        "angles": preferences.get("angles", {}),
        "research_preferences": preferences.get("research_preferences", {}),
        "outline_preferences": preferences.get("outline_preferences", {}),
        "voice": preferences.get("voice", {}),
        "openings": preferences.get("openings", {}),
        "endings": preferences.get("endings", {}),
        "formatting": preferences.get("formatting", {}),
        "anti_style": preferences.get("anti_style", {}),
        "field_metadata": preferences.get("field_metadata", {}),
        "raw_sources": [],
        "sources": [],
        "topics": [],
        "previous_topics": [],
        "selected_topic": None,
        "rejected_topic_ids": [],
        "summary": "",
        "feedback": "",
        "requested_angle": "",
        "topic_retry_count": 0,
        "feedback_events": [],
        "decision": "",
        "status": "running",
    }
    config = {
        "configurable": {"thread_id": f"{user_id}:{initial_state['cycle_id']}"},
        "recursion_limit": 100,
    }
    final_state = graph.invoke(initial_state, config=config)
    while final_state.get("__interrupt__"):
        review = final_state["__interrupt__"][0].value
        if review.get("type") == "topic_email_review":
            reply = wait_for_reply(review["message_id"], review["recipient"], review["topics"])
        elif review.get("type") == "draft_email_review":
            reply = wait_for_draft_reply(review["message_id"], review["recipient"])
        else:
            break
        if reply is None:
            break
        final_state = graph.invoke(Command(resume=reply), config=config)
    return final_state
