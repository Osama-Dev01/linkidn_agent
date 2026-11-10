from copy import deepcopy
from datetime import datetime, timezone

from app.catalog.preference_catalogue import map_profile


def load_preferences(profile: dict, preferences: dict | None = None) -> dict:
    profile = deepcopy(profile)
    preferences = deepcopy(preferences) if preferences is not None else {}
    explicit = profile.get("preferences", {})
    if "preferred_organisation" in explicit:
        explicit["preferred_organisation"] = [
            value.replace(" → ", " to ")
            for value in explicit["preferred_organisation"]
        ]

    mapped = map_profile(profile, preferences)
    timestamp = datetime.now(timezone.utc)
    for change in mapped["changes"]:
        group, field = change["field"].split("/")
        preferences.setdefault(group, {})[field] = change["new_value"]
        preferences.setdefault("field_metadata", {})[change["field"]] = {
            "source": "profile",
            "updated_at": timestamp,
        }
    if mapped["changes"]:
        preferences["updated_at"] = timestamp

    return {"preferences": preferences, "issues": mapped["issues"]}
