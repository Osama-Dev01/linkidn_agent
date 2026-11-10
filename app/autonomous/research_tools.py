from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from app.autonomous.research_schema import ResearchSource


def domain(value: str) -> str:
    return (urlsplit(value if "://" in value else "https://" + value).hostname or "").removeprefix("www.")


def source_url(url: str) -> str:
    parts = urlsplit(url)
    return parts._replace(scheme=parts.scheme.lower(), netloc=parts.netloc.lower(), fragment="").geturl()


def allowed_source(url: str, blocked_domains: list[str]) -> bool:
    host = domain(url)
    return not any(host == blocked or host.endswith("." + blocked) for blocked in blocked_domains)


def cited_sources(response, user_id: str, cycle_id: str, blocked_domains: list[str]) -> list[ResearchSource]:
    sources = {}
    for item in response.output:
        if item.type != "message":
            continue
        for content in item.content:
            if content.type != "output_text":
                continue
            for citation in content.annotations:
                if citation.type != "url_citation" or not allowed_source(citation.url, blocked_domains):
                    continue
                start, end = citation.start_index, citation.end_index
                if not 0 <= start < end <= len(content.text):
                    raise ValueError("Invalid web citation offsets.")
                left = content.text.rfind("\n", 0, start) + 1
                right = content.text.find("\n", end)
                finding = content.text[left:right if right != -1 else len(content.text)].strip()
                url = source_url(citation.url)
                if url not in sources:
                    sources[url] = ResearchSource(
                        id=str(uuid5(NAMESPACE_URL, f"{user_id}:{cycle_id}:web:{url}")),
                        url=url, title=citation.title, retrieved_at=datetime.now(timezone.utc).isoformat(),
                        origin="web_search", cited_findings=[],
                    )
                if finding not in sources[url].cited_findings:
                    sources[url].cited_findings.append(finding)
    return list(sources.values())
