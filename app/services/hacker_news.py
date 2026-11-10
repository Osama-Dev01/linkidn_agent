from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx
import trafilatura

from app.graph.state import ResearchState
from app.services.collection_timeout import collect_with_timeout


MAX_BODY_CHARACTERS = 12_000
SEARCH_URL = "https://hn.algolia.com/api/v1/search"
DAYS_BACK = 100
MIN_POINTS = 20
RESULTS_PER_SEARCH = 3


class TextExtractor(HTMLParser):
    """Convert HN's HTML story text into readable text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "br", "li", "pre"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "li", "pre"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def clean_html(value: str) -> str:
    parser = TextExtractor()
    parser.feed(value)
    return "".join(parser.parts).strip()


def fetch_article(url: str) -> str:
    if urlsplit(url).hostname == "news.ycombinator.com":
        return ""
    downloaded = trafilatura.fetch_url(url)
    return (trafilatura.extract(downloaded) or "") if downloaded else ""


def collect_hackernews_content(state: ResearchState) -> dict:
    return collect_with_timeout(__name__, "_collect_hackernews_content", state)


def _collect_hackernews_content(state: ResearchState, emit) -> dict:
    queries = state["search_querries"][5:10]
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=DAYS_BACK)
    records = []
    records_by_id = {}

    with httpx.Client(timeout=15.0) as client:
        for query in queries:
            response = client.get(
                SEARCH_URL,
                params={
                    "query": query,
                    "tags": "story",
                    "numericFilters": (
                        f"created_at_i>{int(cutoff.timestamp())},"
                        f"points>{MIN_POINTS}"
                    ),
                    "hitsPerPage": RESULTS_PER_SEARCH,
                },
            )
            response.raise_for_status()

            for item in response.json().get("hits", [])[:RESULTS_PER_SEARCH]:
                story_id = item.get("objectID")
                title = item.get("title")
                if not story_id or not title:
                    continue

                if story_id in records_by_id:
                    existing = records_by_id[story_id]
                    if query not in existing["matched_queries"]:
                        existing["matched_queries"].append(query)
                    emit(existing)
                    continue

                discussion_url = f"https://news.ycombinator.com/item?id={story_id}"
                url = item.get("url") or discussion_url
                story_text = clean_html(item.get("story_text") or "")
                body = fetch_article(url) or story_text
                record = {
                    "title": unescape(title),
                    "description": story_text or body[:500] or unescape(title),
                    "matched_topics": [],
                    "matched_queries": [query],
                    "url": url,
                    "body": body[:MAX_BODY_CHARACTERS],
                    "body_truncated": len(body) > MAX_BODY_CHARACTERS,
                    "source": "hackernews",
                    "retrieved_at": now.isoformat(),
                    "published_at": item.get("created_at"),
                    "story_id": story_id,
                    "points": item.get("points") or 0,
                    "num_comments": item.get("num_comments") or 0,
                    "discussion_url": discussion_url,
                }
                records.append(record)
                records_by_id[story_id] = record
                emit(record)

    for record in records:
        print("hackeerrrrrrrrrrrrrrr nnnnnnnnnnwwwwwwwwwwwwwssa", record["title"])

    return {"raw_sources": records}
