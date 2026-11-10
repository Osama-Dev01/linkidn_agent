import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from tavily import TavilyClient
from app.graph.state import ResearchState
from app.services.collection_timeout import collect_with_timeout


# This file should be located at app/services/search.py.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

MAX_BODY_CHARACTERS = 12_000

def normalise_url(url: str) -> str:
    """Remove URL fragments while preserving query parameters."""
    parts = urlsplit(url)

    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path,
        parts.query,
        "",
    ))


def collect_web_content( state : ResearchState):
    return collect_with_timeout(__name__, "_collect_web_content", state)


def _collect_web_content(state: ResearchState, emit):
    queries = state["search_querries"][:5]
    days_back = 30
    results_per_search = 3

    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise ValueError("Add TAVILY_API_KEY to your project .env file.")

    if days_back < 1:
        raise ValueError("days_back must be at least 1.")

    if not 1 <= results_per_search <= 20:
        raise ValueError("results_per_search must be between 1 and 20.")

    client = TavilyClient(api_key=api_key)

    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=days_back)).date().isoformat()
    end_date = now.date().isoformat()

    records = []
    records_by_url = {}

    for query in queries:

        # API failures propagate to the caller.
        response = client.search(
            query=query,
            topic="general",
            search_depth="basic",
            start_date=start_date,
            end_date=end_date,
            include_published_date=True,
            max_results=results_per_search,
            include_answer=False,
            include_raw_content="text",
            timeout=30,
        )

        for result in response.get("results", [])[:results_per_search]:
            url = result.get("url")

            if not url:
                continue

            key = normalise_url(url)

            raw_content = result.get("raw_content") or ""
            snippet = result.get("content") or ""
            body = raw_content or snippet

            if key in records_by_url:
                existing = records_by_url[key]

                if query not in existing["matched_queries"]:
                    existing["matched_queries"].append(query)

                # Upgrade a previous snippet if full text is now available.
                if (
                    raw_content
                    and existing["content_type"] == "web_search_snippet"
                ):
                    existing["body"] = raw_content[:MAX_BODY_CHARACTERS]
                    existing["body_truncated"] = (
                        len(raw_content) > MAX_BODY_CHARACTERS
                    )
                    existing["content_type"] = "web_page"

                if existing["published_at"] is None:
                    existing["published_at"] = result.get("published_date")

                emit(existing)
                continue

            metadata = {
                "user_id": state["user_id"],
                "cycle_id": state["cycle_id"],
                "source": "web",

                # GitHub-compatible fields.
                "repo": None,
                "repo_url": None,
                "description": snippet,
                "stars": None,
                "matched_topics": [],
                "matched_queries": [query],
                "github_topics": [],
                "pushed_at": None,
                "retrieved_at": now.isoformat(),

                # Web-specific fields.
                "publisher_domain": urlsplit(url).hostname,
                "search_categories": ["general"],
            }

            records.append({
                **metadata,
                "content_type": (
                    "web_page" if raw_content else "web_search_snippet"
                ),
                "title": result.get("title") or "",
                "url": url,
                "tag": None,
                "published_at": result.get("published_date"),
                "prerelease": None,
                "body": body[:MAX_BODY_CHARACTERS],
                "body_truncated": len(body) > MAX_BODY_CHARACTERS,
            })

            records_by_url[key] = records[-1]
            emit(records[-1])



    return {"raw_sources": records}




   
