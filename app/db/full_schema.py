
# PostType = Literal[
#     "Tutorial", "Explainer", "News analysis", "Opinion", "Case study",
#     "Project breakdown", "Personal lesson", "Research summary",
#     "Tool comparison", "Prediction",
# ]
# Tone = Literal[
#     "Professional", "Conversational", "Thoughtful", "Direct", "Curious", "Witty", "Encouraging",
# ]
# Opening = Literal[
#     "Direct statement", "Question", "Personal observation", "Problem", "Evidence-backed fact",
# ]
# Closing = Literal[
#     "Practical takeaway", "Open question", "Summary", "Call to action", "No fixed closing",
# ]
# Organisation = Literal[
#     "Problem to solution", "Story to lesson", "Step-by-step", "Claim to evidence", "Comparison",
# ]
# Angle = Literal[
#     "Implementation lessons", "Trade-offs", "Failures", "Practical applications",
#     "Critical analysis", "Contrarian", "Behind the scenes", "Myth-busting", "Trend with take",
# ]
# ResearchDepth = Literal["Quick overview", "Standard", "Deep research"]
# Level = Literal["Low", "Moderate", "High"]
 
# # Three separate decision vocabularies instead of one mixed list.
# TopicChoice = Literal["selected", "skipped"]
# ReviewDecision = Literal["approve", "request_changes", "reject", "postpone"]
# ChangeStatus = Literal["suggested", "applied", "dismissed"]
# ChangeOperation = Literal["set", "add", "remove"]
# ProcessingStatus = Literal["pending", "processed", "failed"]
 
# SkipReason = Literal[
#     "too basic", "overhyped", "not my area", "already covered", "too risky", "never show again",
# ]
 
 
# # ---------------------------------------------------------------------------
# # Preference groups
# # ---------------------------------------------------------------------------
 
# class TopicInterests(TypedDict, total=False):
#     primary_topics: list[str]
#     secondary_topics: list[str]
#     hard_excluded_topics: list[str]
#     soft_excluded_topics: list[str]
#     search_keywords: list[str]
#     freshness: Literal["Timely", "Evergreen", "Balanced"]
#     recency_window: int
#     repeat_policy: Literal["Avoid repeats", "Allow a new angle", "Allow substantial updates"]
#     cooldown_days: int
 
 
# class SelectionTaste(TypedDict, total=False):
#     practical_vs_conceptual: Literal["Practical", "Conceptual", "Balanced"]
#     substance_vs_hype: Literal["Deep topics", "Announcements", "Balanced"]
#     content_focus: list[Literal["Tools", "Research", "Career", "Architecture", "Industry opinions"]]
#     audience_level_of_topic: Literal["Beginner", "Intermediate", "Advanced", "Mixed"]
#     ranking_priority_order: list[Literal[
#         "Originality", "Audience relevance", "Personal relevance", "Discussion value", "Evidence strength",
#     ]]
 
 
# class ContentTypes(TypedDict, total=False):
#     preferred_types: list[PostType]
#     weekly_content_mix: dict[PostType, int]  # post type -> posts per week; keys come from preferred_types
 
 
# class Angles(TypedDict, total=False):
#     preferred_angles: list[Angle]
#     avoided_angles: list[Angle]
#     default_speaker_role: Literal["Practitioner", "Learner", "Critic", "Observer"]
#     opinion_strength: Literal["Mild", "Balanced", "Strong"]
#     criticism_style: Literal["Ideas and tools only", "Constructive only", "Never name people"]
#     prediction_style: Literal["Cautious", "Bold"]
 
 
# class ResearchPreferences(TypedDict, total=False):
#     research_depth: ResearchDepth
#     preferred_sources: list[str]
#     preferred_evidence: list[Literal[
#         "Official documentation", "Research papers", "First-hand reports",
#         "Reproducible tests", "Reputable reporting",
#     ]]
#     minimum_sources: int
#     prefer_primary_sources: bool
#     counterevidence_required: bool
#     # "Ask me" removed: it would interrupt the run between the two human checkpoints.
#     # Flagged claims are shown in the final review package instead.
#     uncertain_claims: Literal["Omit", "Include with qualification"]
#     citations: Literal["Inline references", "Sources at end", "Decide per post"]
#     numbers_handling: Literal["Sourced exact figures", "Sourced ranges"]
 
 
# class OutlinePreferences(TypedDict, total=False):
#     preferred_organisation: list[Organisation]
#     explanation_order: Literal["Example first", "Definition first", "Analogy first"]
#     number_of_main_points: Literal["1", "2 to 3", "4 or more"]
#     detail_level: Literal["Light", "Moderate", "Thorough"]
 
 
# class Voice(TypedDict, total=False):
#     tone: list[Tone]
#     formality: Literal["Casual", "Balanced", "Formal"]
#     point_of_view: Literal["First person", "Third person", "Depends on content"]
#     technical_depth: Literal["Accessible", "Moderately technical", "Deeply technical", "Adapt to audience"]
#     directness: Literal["Blunt", "Balanced", "Diplomatic"]
#     warmth: Level
#     enthusiasm: Level
#     humor_style: Literal["None", "Dry", "Self-deprecating", "Playful"]
#     confidence_and_hedging: Literal["Flat statements", "Balanced", "Qualified statements"]
#     voice_instructions: str
#     jargon_handling: Literal["Assume", "Briefly define", "Always explain"]
 
 
# class Openings(TypedDict, total=False):
#     preferred_opening: list[Opening]
#     hook_length: Literal["One line", "Two lines"]
 
 
# class Endings(TypedDict, total=False):
#     closing_style: list[Closing]
 
 
# class Formatting(TypedDict, total=False):
#     lists: Literal["Prefer", "When helpful", "Avoid"]
#     emojis: Literal["None", "Occasional", "Frequent"]
#     hashtags: Literal["None", "Limited", "Automatic"]
#     hashtag_max: int
#     hashtag_placement: Literal["Inline", "At end"]
 
 
# class AntiStyle(TypedDict, total=False):
#     avoided_patterns: list[str]
#     avoided_phrases: list[str]
#     polish_level: Literal["Natural", "Polished"]
#     additional_restrictions: str
 
 
# class ReviewBehavior(TypedDict, total=False):
#     auto_fix_small_edits: bool
#     max_auto_revisions: int
#     review_package: Literal["Draft only", "Draft with sources and angle"]
 
 
# class PostTypeOverrides(TypedDict, total=False):
#     tone: list[Tone]
#     preferred_organisation: list[Organisation]
#     preferred_opening: list[Opening]
#     closing_style: list[Closing]
 
 
# class PreferenceMetadata(TypedDict, total=False):
#     source: Literal["profile", "topic_feedback", "review_feedback", "sample"]
#     feedback_event_id: str
#     sample_ids: list[str]
#     updated_at: datetime
 
 
# class Preferences(Document, total=False):
#     # user_id and updated_at are inherited; user_id is the unique collection key.
#     topic_interests: TopicInterests
#     selection_taste: SelectionTaste
#     content_types: ContentTypes
#     angles: Angles
#     research_preferences: ResearchPreferences
#     outline_preferences: OutlinePreferences
#     voice: Voice
#     openings: Openings
#     endings: Endings
#     formatting: Formatting
#     anti_style: AntiStyle
#     review_behavior: ReviewBehavior
#     by_content_type: dict[PostType, PostTypeOverrides]  # keys come from preferred_types
#     # Keys are field paths with "/" as the separator, e.g. "voice/tone".
#     # Do not use dots: MongoDB treats them as nested paths in updates and queries.
#     field_metadata: dict[str, PreferenceMetadata]