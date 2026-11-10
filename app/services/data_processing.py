import re
from html.parser import HTMLParser
from app.graph.state import ResearchState , Source
import json
from uuid import NAMESPACE_URL, uuid5



class HTMLTextExtractor(HTMLParser):
    """Extract text from HTML while excluding scripts and styles."""

    BLOCK_TAGS = {
        "p", "div", "section", "article",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "blockquote", "tr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_tag = None
        self.link_stack = []

    def handle_starttag(self, tag, attrs):
        if self.skip_tag:
            return

        if tag in {"script", "style", "noscript"}:
            self.skip_tag = tag
            return

        if tag in self.BLOCK_TAGS or tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")
        elif tag == "pre":
            self.parts.append("\n```\n")
        elif tag == "a":
            self.link_stack.append(dict(attrs).get("href"))

    def handle_endtag(self, tag):
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_tag = None
            return

        if tag in self.BLOCK_TAGS or tag == "li":
            self.parts.append("\n")
        elif tag == "pre":
            self.parts.append("\n```\n")
        elif tag == "a" and self.link_stack:
            href = self.link_stack.pop()
            if href:
                self.parts.append(f" ({href})")

    def handle_data(self, data):
        if not self.skip_tag:
            self.parts.append(data)


def clean_body(body: str | None, *, is_html: bool = False) -> str:
    """Clean text without stripping useful Markdown or code indentation."""
    if not body:
        return ""

    if is_html:
        parser = HTMLTextExtractor()
        parser.feed(body)
        parser.close()
        body = "".join(parser.parts)

    # Normalise line endings.
    body = body.replace("\r\n", "\n").replace("\r", "\n")

    # Remove unwanted control characters, keeping tabs and newlines.
    body = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", body)

    lines = []
    fence_char = None
    fence_length = 0
    previous_blank = False

    for line in body.split("\n"):
        fence = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$", line)

        # Preserve fenced code exactly.
        if fence_char is not None:
            lines.append(line)

            if (
                fence
                and fence.group(1)[0] == fence_char
                and len(fence.group(1)) >= fence_length
                and not fence.group(2).strip()
            ):
                fence_char = None

            previous_blank = False
            continue

        if fence:
            fence_char = fence.group(1)[0]
            fence_length = len(fence.group(1))
            lines.append(line)
            previous_blank = False
            continue

        # Clean prose without removing leading indentation.
        line = (
            line.replace("\u00a0", " ")
            .replace("\u200b", "")
            .replace("\ufeff", "")
        )

        if line.strip():
            lines.append(line)
            previous_blank = False
        elif not previous_blank:
            lines.append("")
            previous_blank = True

    # Remove empty boundary lines without stripping code indentation.
    while lines and not lines[0].strip():
        lines.pop(0)

    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines)


def clean_short_text(value: str | None) -> str:
    """Collapse whitespace in titles and descriptions."""
    text = clean_body(value)
    return re.sub(r"\s+", " ", text).strip()



def process_sources(state: ResearchState):
    processed: list[Source] = []
    records_by_url: dict[str, Source] = {}

    for record in state["raw_sources"]:
        url = (record.get("url") or "").strip()

        if not url:
            continue

        # Same user + cycle + exact URL produces the same ID.
        source_key = json.dumps([
            state["user_id"],
            state["cycle_id"],
            url,
        ])

        item: Source = {
            **record,
            "id": str(uuid5(NAMESPACE_URL, source_key)),
            "extracted_source": record.get("source", ""),
            "title": clean_short_text(record.get("title")),
            "description": clean_short_text(record.get("description")),
            "url": url,
            "body": clean_body(
                record.get("body"),
                is_html=record.get("body_format") == "html",
            ),
        }
        for field in ("matched_topics", "matched_queries"):
            item[field] = list(dict.fromkeys(
                value.strip()
                for value in (record.get(field) or [])
                if isinstance(value, str) and value.strip()
            ))

        # Merge exact duplicate URLs and retain one source ID.
        if url in records_by_url:
            existing = records_by_url[url]

            for field in ("matched_topics", "matched_queries", "github_topics", "search_categories"):
                if field in existing or field in item:
                    existing[field] = list(dict.fromkeys(
                        (existing.get(field) or []) + (item.get(field) or [])
                    ))

            if item["body"] and (
                not existing["body"]
                or (
                    existing.get("content_type") == "web_search_snippet"
                    and item.get("content_type") == "web_page"
                )
            ):
                existing["body"] = item["body"]
                for field in ("content_type", "body_truncated"):
                    if field in item:
                        existing[field] = item[field]

            for field, value in item.items():
                if existing.get(field) in (None, "", []):
                    existing[field] = value

            continue

        processed.append(item)
        records_by_url[url] = item
    for item in processed:
        print(
            "extract sources /////////////////////////////////////",
            item["extracted_source"],
            item["id"],
            item["title"],
            item["description"],
        )
    return {"sources": processed, "topic_candidates": processed}
