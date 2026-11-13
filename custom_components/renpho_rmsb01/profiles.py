"""HA-only profile helpers; scale enrollment metadata is explicit and optional."""

import hashlib
from typing import Any

from .const import (
    AUTO_PROFILE,
    CONF_ACTIVE_PROFILE,
    CONF_AGE,
    CONF_GENDER,
    CONF_HEIGHT,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_PROFILES,
    CONF_SCALE_PROFILE,
    CONF_SCALE_USER_INDEX,
    DEFAULT_AGE,
    DEFAULT_GENDER,
    DEFAULT_HEIGHT,
)


def _legacy_profile_id(name: str) -> str:
    """Give pre-profile-ID installs stable IDs; edits persist the ID across renames."""
    return hashlib.sha256(f"renpho-legacy:{name.casefold()}".encode()).hexdigest()[:12]


def get_profiles(entry) -> list[dict[str, Any]]:
    """Return independent profile dictionaries, including optional scale mappings."""
    profiles = entry.options.get(CONF_PROFILES)
    if not isinstance(profiles, list) or not profiles:
        profiles = [
            {
                CONF_PROFILE_NAME: entry.data.get(CONF_PROFILE_NAME, entry.title),
                CONF_AGE: entry.data.get(CONF_AGE, DEFAULT_AGE),
                CONF_HEIGHT: entry.data.get(CONF_HEIGHT, DEFAULT_HEIGHT),
                CONF_GENDER: entry.data.get(CONF_GENDER, DEFAULT_GENDER),
            }
        ]
    result = []
    for profile in profiles:
        item = dict(profile)
        item.setdefault(CONF_PROFILE_ID, _legacy_profile_id(item[CONF_PROFILE_NAME]))
        result.append(item)
    return result


def selected_name(entry) -> str:
    """Return Auto or the explicitly selected profile name."""
    profiles = get_profiles(entry)
    selected = entry.options.get(CONF_ACTIVE_PROFILE, profiles[0][CONF_PROFILE_NAME])
    if selected == AUTO_PROFILE:
        return AUTO_PROFILE
    return next(
        (profile[CONF_PROFILE_NAME] for profile in profiles if profile[CONF_PROFILE_NAME] == selected),
        profiles[0][CONF_PROFILE_NAME],
    )


def active_profile(entry) -> dict[str, Any]:
    """Return the selected manual profile; Auto deliberately falls back to the first."""
    profiles = get_profiles(entry)
    selected = selected_name(entry)
    if selected == AUTO_PROFILE:
        return profiles[0]
    return next(
        (profile for profile in profiles if profile[CONF_PROFILE_NAME] == selected),
        profiles[0],
    )


def is_auto_mode(entry) -> bool:
    return selected_name(entry) == AUTO_PROFILE


def profile_for_scale_user(entry, user_index: int) -> dict[str, Any] | None:
    """Map only enrolled slots 1-8; never infer identity or accept visitor 254."""
    if not 1 <= user_index <= 8:
        return None
    return next(
        (
            profile
            for profile in get_profiles(entry)
            if profile.get(CONF_SCALE_USER_INDEX) == user_index
        ),
        None,
    )


def profile_needs_sync(profile: dict[str, Any]) -> bool:
    """Detect HA demographic edits that have not yet been sent to the scale."""
    if CONF_SCALE_USER_INDEX not in profile:
        return False
    enrolled = profile.get(CONF_SCALE_PROFILE, {})
    return any(enrolled.get(key) != profile[key] for key in (CONF_AGE, CONF_HEIGHT, CONF_GENDER))


def profile_options(profiles: list[dict], selected: str) -> dict[str, Any]:
    return {CONF_PROFILES: profiles, CONF_ACTIVE_PROFILE: selected}
