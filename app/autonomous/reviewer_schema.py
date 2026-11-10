from typing import Literal

from pydantic import Field, model_validator

from app.autonomous.research_schema import StrictModel, Text


class QualityFinding(StrictModel):
    kind: Literal["evidence", "personal_material", "topic", "voice", "readability", "formatting"]
    severity: Literal["blocking", "major", "minor"]
    suggested_owner: Literal["writer", "researcher"]
    draft_span: str | None
    evidence: Text
    required_change: Text


class RequirementResult(StrictModel):
    requirement_id: Text
    status: Literal["satisfied", "unmet"]
    evidence: Text


class QualityReview(StrictModel):
    draft_version: int | None = Field(ge=1)
    verdict: Literal["pass", "revise", "hold"]
    findings: list[QualityFinding]
    limitations: list[Text]
    requirement_results: list[RequirementResult] = []

    @model_validator(mode="after")
    def check_verdict(self):
        if self.verdict == "pass" and any(item.severity != "minor" for item in self.findings):
            raise ValueError("A passing review cannot contain blocking or major findings.")
        if self.verdict == "pass" and self.draft_version is None:
            raise ValueError("A passing review requires a draft version.")
        if self.verdict == "pass" and any(item.status == "unmet" for item in self.requirement_results):
            raise ValueError("A passing review must satisfy all active requirements.")
        return self
