from pydantic import Field, model_validator

from app.autonomous.research_schema import StrictModel, Text


class EvidenceMapEntry(StrictModel):
    draft_span: Text
    claim_ids: list[Text]
    personal_material_ids: list[Text]

    @model_validator(mode="after")
    def check_references(self):
        if not self.claim_ids and not self.personal_material_ids:
            raise ValueError("An evidence entry requires a reference.")
        for values in (self.claim_ids, self.personal_material_ids):
            if len(values) != len(set(values)):
                raise ValueError("Evidence references must be unique.")
        return self


class WorkRequest(StrictModel):
    question: Text
    why_needed: Text


class WriterResult(StrictModel):
    text: Text | None
    evidence_map: list[EvidenceMapEntry]
    work_request: WorkRequest | None

    @model_validator(mode="after")
    def check_result(self):
        if (self.text is None) == (self.work_request is None):
            raise ValueError("Return either a draft or a work request.")
        if self.work_request and self.evidence_map:
            raise ValueError("A work request cannot contain draft evidence.")
        for entry in self.evidence_map:
            if entry.draft_span not in self.text:
                raise ValueError("Evidence spans must occur exactly in the draft.")
        return self


class VersionedDraft(StrictModel):
    text: Text
    evidence_map: list[EvidenceMapEntry]
    version: int = Field(ge=1)
    parent_version: int | None = Field(ge=1)
