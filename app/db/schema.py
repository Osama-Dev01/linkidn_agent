"""MongoDB document shapes only; no runtime validation or database operations.

Collections: users, profiles, preferences, feedback_events.
Missing preference fields represent information not yet supplied or learned.
"""

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar, TypedDict

from bson import ObjectId


class Document(TypedDict, total=False):
    _id: ObjectId
    user_id: str
    created_at: datetime
    updated_at: datetime


class User(Document, total=False):
    name: str
    email: str
    password_hash: str


# Explicit profile inputs; field names match the frontend.

class Identity(TypedDict, total=False):
    name: str
    professional_role: str
    industry: list[str]
    background: str
    public_positioning: str
    default_speaker_role: str


class Expertise(TypedDict, total=False):
    experienced_topics: list[str]
    experienced_notes: str
    learning_topics: list[str]
    learning_notes: str


class Audience(TypedDict, total=False):
    target_audience: list[str]
    audience_level: str
    audience_problems: list[str]
    posting_goals: list[str]
    content_themes: list[str]


class Interests(TypedDict, total=False):
    primary_topics: list[str]
    secondary_topics: list[str]
    hard_excluded_topics: list[str]
    soft_excluded_topics: list[str]
    preferred_content_types: list[str]
    search_keywords: list[str]
    preferred_sources: list[str]
    distrusted_sources: list[str]
    freshness: str
    recency_window: int


class ExplicitPreferences(TypedDict, total=False):
    tone: list[str]
    formality: str
    point_of_view: str
    technical_depth: str
    voice_instructions: str
    preferred_opening: list[str]
    preferred_organisation: list[str]
    post_length: str
    word_range: str
    closing_style: list[str]
    paragraph_style: str
    lists: str
    emojis: str
    hashtags: str
    hashtag_max: int
    citations: str
    preferred_angles: list[str]
    repeat_policy: str
    cooldown_days: int
    research_depth: str
  
    preferred_evidence: list[str]
    uncertain_claims: str
    avoided_phrases: list[str]
    avoided_patterns: list[str]
    additional_restrictions: str


class WritingSample(TypedDict, total=False):
    id: str
    text: str
    content_type: str
    authorship: str
    sounds_like_me: str
    notes: str


class Stance(TypedDict, total=False):
    id: str
    topic: str
    position: str
    reasoning: str
    conditions: list[str]
    exceptions: list[str]
    permission_to_share: str


class Experience(TypedDict, total=False):
    id: str
    situation: str
    personal_role: str
    actions: list[str]
    outcome: str
    lesson: str
    permitted_details: list[str]
    usage_permission: str
    anonymisation: str


Item = TypeVar("Item")


class Records(TypedDict, Generic[Item], total=False):
    items: list[Item]


class Profile(Document, total=False):
    identity: Identity
    expertise: Expertise
    audience: Audience
    interests: Interests
    preferences: ExplicitPreferences
    writing_samples: Records[WritingSample]
    stances: Records[Stance]
    experiences: Records[Experience]


# Personalization loaded into graph state, grouped by purpose.
# Literal choices are type annotations only, not runtime validation.
# Topics, phrases, source names, and free-text instructions remain strings.

PostType = Literal[
    "Tutorial", "Explainer", "News analysis", "Opinion", "Case study",
    "Project breakdown", "Personal lesson", "Research summary",
    "Tool comparison", "Prediction",
]
Tone = Literal[
    "Professional", "Conversational", "Thoughtful", "Direct", "Curious", "Witty", "Encouraging",
]
Opening = Literal[
    "Direct statement", "Question", "Personal observation", "Problem", "Evidence-backed fact",
]
Closing = Literal[
    "Practical takeaway", "Open question", "Summary", "Call to action", "No fixed closing",
]
Organisation = Literal[
    "Problem to solution", "Story to lesson", "Step-by-step", "Claim to evidence", "Comparison",
]
Angle = Literal[
    "Implementation lessons", "Trade-offs", "Failures", "Practical applications",
    "Critical analysis", "Contrarian", "Behind the scenes", "Myth-busting", "Trend with take",
]
ResearchDepth = Literal["Quick overview", "Standard", "Deep research"]
 
# Three separate decision vocabularies instead of one mixed list.
TopicChoice = Literal["selected", "skipped"]
ReviewDecision = Literal["approve", "request_changes", "reject", "postpone", "feedback"]
ChangeStatus = Literal["suggested", "applied", "dismissed"]
ChangeOperation = Literal["set", "add", "remove"]
ProcessingStatus = Literal["pending", "processed", "failed"]
 
SkipReason = Literal[
    "too basic", "overhyped", "not my area", "already covered", "too risky", "never show again",
]
 
 
# ---------------------------------------------------------------------------
# Preference groups
# ---------------------------------------------------------------------------
 
class TopicInterests(TypedDict, total=False):
    primary_topics: list[str]
    secondary_topics: list[str]
    hard_excluded_topics: list[str]
    soft_excluded_topics: list[str]
    search_keywords: list[str]
    freshness: Literal["Timely", "Evergreen", "Balanced"]
    recency_window: int
    repeat_policy: Literal["Avoid repeats", "Allow a new angle", "Allow substantial updates"]
    cooldown_days: int
 
 
class SelectionTaste(TypedDict, total=False):
    practical_vs_conceptual: list[str]
    substance_vs_hype: list[str]
    content_focus: list[str]
    audience_level_of_topic: list[str]
 
 
class ContentTypes(TypedDict, total=False):
    preferred_types: list[PostType]
 
 
class Angles(TypedDict, total=False):
    preferred_angles: list[Angle]
    default_speaker_role: Literal["Practitioner", "Learner", "Critic", "Observer"]
 
 
class ResearchPreferences(TypedDict, total=False):
    research_depth: ResearchDepth
    preferred_sources: list[str]
    preferred_evidence: list[Literal[
        "Official documentation", "Research papers", "First-hand reports",
        "Reproducible tests", "Reputable reporting",
    ]]
    uncertain_claims: Literal["Omit", "Include with qualification"]
    citations: Literal["Inline references", "Sources at end", "Decide per post"]
 
 
class OutlinePreferences(TypedDict, total=False):
    preferred_organisation: list[Organisation]
 
 
class Voice(TypedDict, total=False):
    tone: list[Tone]
    formality: Literal["Casual", "Balanced", "Formal"]
    point_of_view: Literal["First person", "Third person", "Depends on content"]
    technical_depth: Literal["Accessible", "Moderately technical", "Deeply technical", "Adapt to audience"]
    voice_instructions: str
 
 
class Openings(TypedDict, total=False):
    preferred_opening: list[Opening]
 
 
class Endings(TypedDict, total=False):
    closing_style: list[Closing]
 
 
class Formatting(TypedDict, total=False):
    lists: Literal["Prefer", "When helpful", "Avoid"]
    emojis: Literal["None", "Occasional", "Frequent"]
    hashtags: Literal["None", "Limited", "Automatic"]
    hashtag_max: int
 
 
class AntiStyle(TypedDict, total=False):
    avoided_patterns: list[str]
    avoided_phrases: list[str]
    additional_restrictions: str
 
 
class PreferenceMetadata(TypedDict, total=False):
    source: Literal["profile", "topic_feedback", "review_feedback", "sample"]
    feedback_event_id: str
    sample_ids: list[str]
    updated_at: datetime
 
 
class Preferences(Document, total=False):
    # user_id and updated_at are inherited; user_id is the unique collection key.
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
    # Keys are field paths with "/" as the separator, e.g. "voice/tone".
    # Do not use dots: MongoDB treats them as nested paths in updates and queries.
    field_metadata: dict[str, PreferenceMetadata]
 
 
# ---------------------------------------------------------------------------
# Feedback, sample-analysis and profile-update events (append-only)
# ---------------------------------------------------------------------------
 
class TopicDecision(TypedDict, total=False):
    topic_id: str
    title: str
    decision: TopicChoice
    reasons: list[SkipReason]
    note: str                       # optional free text from the user
 
 
class PreferenceChange(TypedDict, total=False):
    field: str                      # path with "/" separator, e.g. "formatting/emojis"
    operation: ChangeOperation
    old_value: Any
    new_value: Any
    content_type: PostType
    status: ChangeStatus            # suggested -> applied or dismissed
    decided_at: datetime | None
 
 
class FeedbackEvent(Document, total=False):
    # user_id and created_at are inherited from Document.
    event_id: str
    run_id: str
    post_id: str
    draft_version: int
    stage: Literal["topic_selection", "post_finalization", "sample_analysis", "profile_update"]
 
    # Topic selection stage
    topic_decisions: list[TopicDecision]
    selected_angle: str
    research_depth: ResearchDepth
    content_type: PostType
 
    # Post finalization stage
    review_decision: ReviewDecision
    message_id: str
    reply_id: str
    raw_reply: str
    scope: Literal["this_post", "future_posts", "content_type"]
    feedback: str
    change_tags: list[Literal["voice", "length", "structure", "angle", "facts", "privacy"]]
    before_text: str                # draft as sent for review
    after_text: str                 # the user's edited version
 
    # Sample analysis stage
    sample_ids: list[str]
 
    # Preference changes this event produced, including pending suggestions and dismissed ones.
    # Dismissed entries stop the same "remember this?" prompt from being shown again.
    changes: list[PreferenceChange]
 
    processing_status: ProcessingStatus
    processed_at: datetime | None



   

class PublishedPost(Document, total=False):
    # user_id and created_at inherited
    post_id: str
    run_id: str
    title: str
    summary: str          
    final_text: str
    
    published_at: datetime | None
 
