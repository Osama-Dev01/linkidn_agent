import os
from pathlib import Path
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

from app.graph.state import ResearchState
from app.autonomous.supervisor import review_is_current
from app.db.client import get_database


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def publish_post(text: str) -> str:
    response = httpx.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json={
            "author": os.environ["LINKEDIN_PERSON_URN"],
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                },
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
            },
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.headers["x-restli-id"]


def publish_approved_post(state: ResearchState) -> dict:
    if state.get("autonomous_active"):
        draft = state.get("draft") or {}
        if (not review_is_current(state) or state.get("draft_review_decision") != "approve"
                or state.get("awaiting_draft_clarification")
                or state.get("draft_review_version") != draft.get("version")
                or state.get("draft_review_text") != draft.get("text")):
            raise ValueError("Publication requires approval of the exact current, passing draft.")
        text = state["draft_review_text"]
    else:
        title = (state.get("selected_topic") or {}).get("title")
        text = f"{title}\n\n{state['draft_review_text']}" if title else state["draft_review_text"]
    post_id = publish_post(text)
    get_database().published_posts.insert_one({
        "user_id": state["user_id"],
        "run_id": state["cycle_id"],
        "post_id": post_id,
        "title": (state.get("selected_topic") or {}).get("title") or text.splitlines()[0],
        "final_text": text,
        "published_at": datetime.now(timezone.utc),
    })
    return {"linkedin_post_id": post_id, "status": "published"}
