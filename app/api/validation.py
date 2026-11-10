import re
from typing import Any

from fastapi import HTTPException


SECTION_FIELDS = {
    "identity": {
        "required": {"name", "professional_role", "industry", "background", "public_positioning", "default_speaker_role"},
        "lists": {"industry"},
        "choices": {"default_speaker_role": {"Practitioner", "Learner", "Critic", "Observer"}},
    },
    "expertise": {
        "required": set(),
        "optional": {"experienced_notes", "learning_notes"},
        "lists": {"experienced_topics", "learning_topics"},
    },
    "audience": {
        "required": {"target_audience", "audience_level", "audience_problems", "posting_goals", "content_themes"},
        "lists": {"target_audience", "audience_problems", "posting_goals", "content_themes"},
        "choices": {
            "audience_level": {"Beginner", "Intermediate", "Advanced", "Mixed"},
            "posting_goals": {"Share knowledge", "Build credibility", "Find jobs", "Attract clients", "Grow network", "Start discussions", "Document learning"},
        },
    },
    "interests": {
        "required": {"primary_topics", "preferred_content_types", "freshness"},
        "lists": {"primary_topics", "secondary_topics", "hard_excluded_topics", "soft_excluded_topics", "preferred_content_types", "search_keywords", "preferred_sources", "distrusted_sources"},
        "choices": {
            "preferred_content_types": {"Tutorial", "Explainer", "News analysis", "Opinion", "Case study", "Project breakdown", "Personal lesson", "Research summary", "Tool comparison"},
            "freshness": {"Timely", "Evergreen", "Balanced"},
        },
        "numbers": {"recency_window": (1, 365)},
    },
    "preferences": {
        "optional": {"voice_instructions", "word_range", "cooldown_days", "hashtag_max", "preferred_angles", "avoided_phrases", "avoided_patterns", "additional_restrictions"},
        "required": {"tone", "formality", "point_of_view", "technical_depth", "preferred_opening", "preferred_organisation", "post_length", "closing_style", "paragraph_style", "lists", "emojis", "hashtags", "citations", "repeat_policy", "research_depth", "minimum_sources", "preferred_evidence", "uncertain_claims"},
        "lists": {"tone", "preferred_opening", "preferred_organisation", "closing_style", "preferred_angles", "preferred_evidence", "avoided_phrases", "avoided_patterns"},
        "choices": {
            "tone": {"Professional", "Conversational", "Thoughtful", "Direct", "Curious", "Witty", "Encouraging"},
            "formality": {"Casual", "Balanced", "Formal"},
            "point_of_view": {"First person", "Third person", "Depends on content"},
            "technical_depth": {"Accessible", "Moderately technical", "Deeply technical", "Adapt to audience"},
            "preferred_opening": {"Direct statement", "Question", "Personal observation", "Problem", "Evidence-backed fact"},
            "preferred_organisation": {"Problem → solution", "Story → lesson", "Step-by-step", "Claim → evidence", "Comparison"},
            "post_length": {"Short", "Medium", "Long", "Custom"},
            "closing_style": {"Practical takeaway", "Open question", "Summary", "Call to action", "No fixed closing"},
            "paragraph_style": {"Short", "Mixed lengths", "No preference"},
            "lists": {"Prefer", "When helpful", "Avoid"},
            "emojis": {"None", "Occasional", "Frequent"},
            "hashtags": {"None", "Limited", "Automatic"},
            "citations": {"Inline references", "Sources at end", "Decide per post"},
            "repeat_policy": {"Avoid repeats", "Allow a new angle", "Allow substantial updates"},
            "research_depth": {"Quick overview", "Standard", "Deep research"},
            "preferred_evidence": {"Official documentation", "Research papers", "First-hand reports", "Reproducible tests", "Reputable reporting"},
            "uncertain_claims": {"Omit", "Include with qualification", "Ask me"},
        },
        "numbers": {"minimum_sources": (1, 20), "hashtag_max": (0, 30), "cooldown_days": (0, 3650)},
        "strings": {"word_range", "voice_instructions", "additional_restrictions"},
    },
}

REPEAT_SECTIONS = {
    "writing_samples": {
        "optional": {"notes"},
        "required": {"text", "content_type", "authorship", "sounds_like_me"},
        "choices": {
            "content_type": {"LinkedIn post", "Article", "Comment", "Email", "Other"},
            "authorship": {"Written by me", "AI-assisted and edited by me", "Written by someone else", "Mixed / unknown"},
            "sounds_like_me": {"Yes", "Partly", "No"},
        },
    },
    "stances": {
        "optional": {"conditions", "exceptions"},
        "required": {"topic", "position", "reasoning", "permission_to_share"},
        "lists": {"conditions", "exceptions"},
        "choices": {"permission_to_share": {"May use in drafts", "Ask before using", "Private context only"}},
    },
    "experiences": {
        "optional": {"outcome", "anonymisation", "permitted_details"},
        "required": {"situation", "personal_role", "actions", "lesson", "usage_permission"},
        "lists": {"actions", "permitted_details"},
        "choices": {"usage_permission": {"May use in drafts", "Ask before using", "Private context only"}},
        "permitted_details": {"Role", "Actions", "Outcomes", "Exact metrics", "Organisation name", "Client name", "Dates"},
    },
}


def _error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def _validate_record(data: Any, spec: dict[str, Any], prefix: str = "") -> list[dict[str, str]]:
    if not isinstance(data, dict):
        return [_error(prefix.rstrip("."), "Expected an object.")]

    errors = []
    supported = set(spec.get("required", set())) | set(spec.get("optional", set()))
    supported |= set(spec.get("lists", set())) | set(spec.get("choices", {}))
    supported |= set(spec.get("numbers", {})) | set(spec.get("strings", set()))

    for key in data:
        if key not in supported and key != "id":
            errors.append(_error(f"{prefix}{key}", "Unknown field."))

    for key in spec.get("required", set()):
        if key not in data or data[key] is None or data[key] == "" or data[key] == []:
            errors.append(_error(f"{prefix}{key}", "This field is required."))

    for key in spec.get("lists", set()):
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, list) or len(value) > 50 or any(not isinstance(item, str) or not item.strip() or len(item) > 300 for item in value):
            errors.append(_error(f"{prefix}{key}", "Use an array of up to 50 non-empty values, each under 300 characters."))
            continue
        if key in spec.get("required", set()) and not value:
            errors.append(_error(f"{prefix}{key}", "Select at least one value."))
        allowed = spec.get("choices", {}).get(key)
        if allowed and any(item not in allowed for item in value):
            errors.append(_error(f"{prefix}{key}", "Choose from the available options."))
        if key == "content_themes" and not 3 <= len(value) <= 6:
            errors.append(_error(f"{prefix}{key}", "Choose 3–6 themes."))
        if key == "permitted_details" and any(item not in spec["permitted_details"] for item in value):
            errors.append(_error(f"{prefix}{key}", "Choose from the available options."))

    for key, allowed in spec.get("choices", {}).items():
        if key not in data or isinstance(data[key], list):
            continue
        if data[key] not in allowed:
            errors.append(_error(f"{prefix}{key}", "Choose from the available options."))

    for key, (minimum, maximum) in spec.get("numbers", {}).items():
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            errors.append(_error(f"{prefix}{key}", f"Enter a whole number from {minimum} to {maximum}."))

    for key in spec.get("strings", set()) | (supported - set(spec.get("lists", set())) - set(spec.get("choices", {})) - set(spec.get("numbers", {}))):
        if key not in data:
            continue
        if not isinstance(data[key], str) or not data[key].strip() or len(data[key]) > 10000:
            errors.append(_error(f"{prefix}{key}", "Enter non-empty text under 10,000 characters."))

    return errors


def validate_section(section: str, data: Any) -> list[dict[str, str]]:
    if section in SECTION_FIELDS:
        spec = SECTION_FIELDS[section]
        errors = _validate_record(data, spec)
        if section == "expertise" and not data.get("experienced_topics") and not data.get("learning_topics"):
            errors.append(_error("experienced_topics", "Add an experienced or learning topic."))
        if section == "interests" and data.get("freshness") in ("Timely", "Balanced") and "recency_window" not in data:
            errors.append(_error("recency_window", "This field is required."))
        if section == "preferences":
            if data.get("post_length") == "Custom":
                word_range = data.get("word_range", "")
                match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", word_range) if isinstance(word_range, str) else None
                if not match or int(match[1]) < 1 or int(match[1]) > int(match[2]) or int(match[2]) > 10000:
                    errors.append(_error("word_range", "Use a range such as 100-200 (maximum 10000)."))
            if data.get("hashtags") == "Limited" and "hashtag_max" not in data:
                errors.append(_error("hashtag_max", "This field is required."))
        return errors

    spec = REPEAT_SECTIONS.get(section)
    if not spec:
        raise HTTPException(status_code=404, detail="Profile section not found.")
    if not isinstance(data, dict) or set(data) != {"items"} or not isinstance(data["items"], list):
        return [_error("items", "Expected an items array.")]
    if len(data["items"]) > 20:
        return [_error("items", "Add up to 20 records.")]
    errors = []
    for index, item in enumerate(data["items"]):
        errors.extend(_validate_record(item, spec, f"{index}."))
    return errors

