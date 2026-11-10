from langgraph.types import interrupt, Overwrite

from app.graph.state import ResearchState, Topic


def initail_states(state: ResearchState) -> dict:
    """Clear discovery data before starting or retrying collection."""
    return {
        # raw_sources uses operator.add, so [] alone would not clear it.
        "raw_sources": Overwrite(value=[]),
        "sources": [],
        "topic_candidates": [],
        "topics": [],
        "selected_topic": None,
        "decision": "",
        "status": "gathering",
    }


def build_topic_choices(state: ResearchState) -> dict:
    """For now, use source titles as selectable topics."""
    rejected_ids = set(state["rejected_topic_ids"])
    topics: list[Topic] = []
    seen_ids = set()

    for source in state["sources"]:
        source_id = source["id"]
        title = source["title"].strip()

        if (
            not title
            or source_id in rejected_ids
            or source_id in seen_ids
        ):
            continue

        topics.append({
            "id": source_id,
            "title": title,
        })
        seen_ids.add(source_id)

    return {
        "topics": topics,
        "status": "awaiting_topic_review",
    }


def review_topics(state: ResearchState) -> dict:
    response = interrupt({
        "topics": state["topics"],
        "current_preferred_angles": (
            state["preferences"]["preferred_angles"]
        ),
        "current_research_depth": (
            state["preferences"]["research_depth"]
        ),
    })

    if response["action"] == "retry":
        rejected_ids = list(dict.fromkeys(
            state["rejected_topic_ids"]
            + [topic["id"] for topic in state["topics"]]
        ))

        return {
            "selected_topic": None,
            "rejected_topic_ids": rejected_ids,
            "decision": "retry",
            "status": "retry_requested",
        }

    if response["action"] != "select":
        raise ValueError("Unknown review action.")

    selected_topic = next(
        (
            topic
            for topic in state["topics"]
            if topic["id"] == response["topic_id"]
        ),
        None,
    )

    if selected_topic is None:
        raise ValueError("Selected topic is not in the current choices.")

    # Copy preferences rather than mutating state directly.
    preferences = dict(state["preferences"])

    if response.get("preferred_angles"):
        preferences["preferred_angles"] = response["preferred_angles"]

    if response.get("research_depth"):
        preferences["research_depth"] = response["research_depth"]

    return {
        "selected_topic": selected_topic,
        "preferences": preferences,
        "decision": "selected",
        "status": "topic_selected",
    }


def route_after_review(state: ResearchState) -> str:
    if state.get("decision") == "selected":
        return "summarize_topic"
    if state.get("topic_retry_count", 0) > 3:
        return "send_topic_direction"
    if state.get("decision") == "refine" and state.get("topic_candidates"):
        return "filter_topics"
    return "search_topics"


def route_after_filter(state: ResearchState) -> str:
    return "send_topic_review" if state.get("topics") else "send_topic_direction"


def ask_topic_selection(payload: dict) -> dict:
    """Terminal input runs outside the graph node."""
    topics = payload["topics"]

    print("\nAvailable topics:")

    for number, topic in enumerate(topics, start=1):
        print(f"{number}. {topic['title']}")

    if not topics:
        print("No new topic choices were found.")

    print("0. Reject all and gather again")

    while True:
        choice = input("\nSelect a topic number: ").strip()

        if choice == "0":
            return {"action": "retry"}

        if choice.isdigit() and 1 <= int(choice) <= len(topics):
            selected_topic = topics[int(choice) - 1]
            break

        print("Enter a valid topic number or 0.")

    current_angles = payload["current_preferred_angles"]
    current_depth = payload["current_research_depth"]

    print(f"\nCurrent angles: {current_angles}")
    angles_input = input(
        "Preferred angles, comma-separated "
        "(Enter to keep current): "
    ).strip()

    print(f"Current research depth: {current_depth}")
    depth_input = input(
        "Research depth (Enter to keep current): "
    ).strip()

    preferred_angles = list(dict.fromkeys(
        angle.strip()
        for angle in angles_input.split(",")
        if angle.strip()
    ))

    return {
        "action": "select",
        "topic_id": selected_topic["id"],
        "preferred_angles": preferred_angles,
        "research_depth": depth_input,
    }
