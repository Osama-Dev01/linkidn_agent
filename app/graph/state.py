from operator import add
from typing import Annotated, Literal, NotRequired, TypedDict

from app.db.schema import (
    Angles,
    AntiStyle,
    ContentTypes,
    Endings,
    FeedbackEvent,
    Formatting,
    Openings,
    OutlinePreferences,
    PreferenceMetadata,
    ResearchPreferences,
    SelectionTaste,
    TopicInterests,
    Voice,
)


class Source(TypedDict):
    id: str
    extracted_source: str
    summary: str
    title: str
    description: str
    matched_topics: list[str]
    url: str
    body: str


class Rawsource(TypedDict):
    title: str
    description: str
    matched_topics: list[str]
    url: str
    body: str
    id: NotRequired[str]
    extracted_source: str
    source: NotRequired[Literal["web", "hackernews", "substack"]]
   
    body_truncated: NotRequired[bool]
    matched_queries: NotRequired[list[str]]
    retrieved_at: NotRequired[str]
    published_at: NotRequired[str | None]
    story_id: NotRequired[str]
    points: NotRequired[int]
    num_comments: NotRequired[int]
    discussion_url: NotRequired[str]
  


class Topic(TypedDict):
    id: str
    title: str
    


class Brief(TypedDict):
    selected_source_id: str
    content_type: str
    speaker_role: Literal["Practitioner", "Learner", "Critic", "Observer"]
    central_question: str
    provisional_angle: str
    research_questions: list[str]


class ResearchState(TypedDict, total=False):
    user_id: str
    cycle_id: str
    instructions: str
    topic_interests: TopicInterests
    selection_taste: SelectionTaste
    content_types: ContentTypes
    angles: Angles
    research_preferences: ResearchPreferences
    outline_preferences: OutlinePreferences
    voice: Voice
    openings: Openings
    endings: Endings
    formatting: Formatting
    anti_style: AntiStyle
    field_metadata: dict[str, PreferenceMetadata]
    raw_sources: Annotated[list[Rawsource], add]
    sources: list[Source]
    topic_candidates: list[Source]
    topics: list[Topic]
    previous_topics: list[Topic]
    selected_topic: Topic | None
    brief: Brief | None
    brief_status: Literal["ready_for_research", "needs_source"]
    research_objective: str
    research_sources: list[dict]
    claims: list[dict]
    gaps: list[dict]
    writer_personal_material_ids: list[str]
    draft: dict | None
    writer_status: Literal["ready", "needs_material"]
    writer_work_request: dict | None
    writer_feedback: str
    writer_issues: list[str]
    writer_context: dict
    autonomous_active: bool
    autonomy_phase: str
    supervisor_action: str
    supervisor_question: str | None
    supervisor_reason: str
    draft_requirements: dict
    draft_history: list[dict]
    open_draft_issues: list[dict]
    resolved_draft_issue_ids: list[str]
    revision_count: int
    processed_draft_feedback_id: str | None
    pending_draft_feedback: str
    awaiting_draft_clarification: bool
    quality_review: dict | None
    writing_review: dict | None
    topic_review_message_id: str
    topic_review_recipient: str
    draft_review_message_id: str | None
    draft_review_recipient: str
    draft_review_version: int
    draft_review_text: str
    draft_review_decision: Literal["approve", "request_changes", "reject", "feedback"] | None
    linkedin_post_id: str
    rejected_topic_ids: list[str]
    summary : str
    search_querries : Annotated[list[str], add]
    feedback: str
    requested_angle: str
    topic_retry_count: int
    feedback_events: list[FeedbackEvent]
    decision: Literal["", "retry", "refine", "selected"]
    status: str
