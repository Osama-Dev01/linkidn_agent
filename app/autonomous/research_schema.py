from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Text = Annotated[str, Field(min_length=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class ResearchPreferences(StrictModel):
    research_depth: Literal["Quick overview", "Standard", "Deep research"] = "Standard"
    preferred_evidence: list[Text] = []
    preferred_sources: list[Text] = []
    distrusted_sources: list[Text] = []
    minimum_sources: Annotated[int, Field(ge=1, le=20)] = 1


class ResearchSource(StrictModel):
    id: Text
    url: Text
    title: str
    retrieved_at: Text
    origin: Literal["web_search"]
    cited_findings: list[Text]

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Expected an HTTP or HTTPS URL.")
        return value


class Evidence(StrictModel):
    source_id: Text
    passage: Text = Field(description="An excerpt from a cited finding, not a verified source quotation.")
    kind: Literal["cited_finding"]


class Claim(StrictModel):
    id: Text
    text: Text
    status: Literal["supported", "qualified", "unsupported", "contradicted"]
    evidence: list[Evidence]
    qualifications: list[Text]
    reason: Text

    @model_validator(mode="after")
    def check_status(self):
        if self.status != "unsupported" and not self.evidence:
            raise ValueError("Supported, qualified and contradicted claims require evidence.")
        if self.status == "qualified" and not self.qualifications:
            raise ValueError("Qualified claims require qualifications.")
        return self


class Gap(StrictModel):
    question: Text
    why_unresolved: Text
    impact: Text


class ResearchLedger(StrictModel):
    claims: list[Claim]
    gaps: list[Gap]

    @model_validator(mode="after")
    def unique_claims(self):
        if len({claim.id for claim in self.claims}) != len(self.claims):
            raise ValueError("Claim IDs must be unique.")
        if len({claim.text.casefold() for claim in self.claims}) != len(self.claims):
            raise ValueError("Claims must be distinct.")
        return self


class ResearchResult(ResearchLedger):
    sources: list[ResearchSource]

    @model_validator(mode="after")
    def check_evidence(self):
        sources = {source.id: source for source in self.sources}
        if len(sources) != len(self.sources):
            raise ValueError("Source IDs must be unique.")
        for claim in self.claims:
            for evidence in claim.evidence:
                source = sources.get(evidence.source_id)
                if source is None:
                    raise ValueError("Evidence references an unavailable source.")
                if not any(
                    " ".join(evidence.passage.split()) in " ".join(finding.split())
                    for finding in source.cited_findings
                ):
                    raise ValueError("Evidence must occur in a finding cited to this source.")
        return self
