import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from tavily import TavilyClient
import trafilatura

from app.graph.state import ResearchState
from app.services.collection_timeout import collect_with_timeout
from app.services.web_search import normalise_url


load_dotenv(Path(__file__).resolve().parents[2] / ".env")

MAX_BODY_CHARACTERS = 12_000
RESULTS_PER_SEARCH = 3


def collect_substack_content(state: ResearchState) -> dict:
    return collect_with_timeout(__name__, "_collect_substack_content", state)


def _collect_substack_content(state: ResearchState, emit) -> dict:
    queries = state["search_querries"][5:10]
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("Add TAVILY_API_KEY to your project .env file.")

    client = TavilyClient(api_key=api_key)
    now = datetime.now(timezone.utc).isoformat()
    records = []
    records_by_url = {}

    for query in queries:
        response = client.search(
            query=query,
            topic="general",
            search_depth="basic",
            include_domains=["substack.com"],
            max_results=RESULTS_PER_SEARCH,
            include_answer=False,
            include_raw_content="text",
            timeout=30,
        )

        for result in response.get("results", [])[:RESULTS_PER_SEARCH]:
            url = result.get("url")
            if not url:
                continue

            key = normalise_url(url)
            if key in records_by_url:
                existing = records_by_url[key]
                if query not in existing["matched_queries"]:
                    existing["matched_queries"].append(query)
                if not existing["published_at"]:
                    existing["published_at"] = result.get("published_date")
                if not existing["body"] and result.get("raw_content"):
                    body = result["raw_content"]
                    existing["body"] = body[:MAX_BODY_CHARACTERS]
                    existing["body_truncated"] = len(body) > MAX_BODY_CHARACTERS
                emit(existing)
                continue

            body = result.get("raw_content") or ""
            if not body:
                downloaded = trafilatura.fetch_url(url)
                body = (trafilatura.extract(downloaded) or "") if downloaded else ""

            record = {
                "title": result.get("title") or "",
                "description": result.get("content") or "",
                "matched_topics": [],
                "matched_queries": [query],
                "url": url,
                "body": body[:MAX_BODY_CHARACTERS],
                "body_truncated": len(body) > MAX_BODY_CHARACTERS,
                "source": "substack",
                "retrieved_at": now,
                "published_at": result.get("published_date"),
            }
            records.append(record)
            records_by_url[key] = record
            emit(record)

    return {"raw_sources": records}
