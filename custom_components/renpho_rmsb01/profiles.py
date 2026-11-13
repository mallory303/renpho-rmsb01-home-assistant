"""HA-side measurement profiles; no stored scale users are modified."""

from __future__ import annotations

from typing import Any

from .const import (
    CONF_ACTIVE_PROFILE,
    CONF_AGE,
    CONF_GENDER,
    CONF_HEIGHT,
    CONF_PROFILE_NAME,
    CONF_PROFILES,
    DEFAULT_AGE,
    DEFAULT_GENDER,
    DEFAULT_HEIGHT,
    DEFAULT_PROFILE_NAME,
)


def get_profiles(entry: Any) -> list[dict[str, Any]]:
    """Return copies of configured profiles, migrating the original single profile."""
    configured = entry.options.get(CONF_PROFILES)
    if isinstance(configured, list) and configured:
        return [dict(profile) for profile in configured]
    values = {**entry.data, **entry.options}
    return [{
        CONF_PROFILE_NAME: values.get(CONF_PROFILE_NAME, DEFAULT_PROFILE_NAME),
        CONF_AGE: values.get(CONF_AGE, DEFAULT_AGE),
        CONF_HEIGHT: values.get(CONF_HEIGHT, DEFAULT_HEIGHT),
        CONF_GENDER: values.get(CONF_GENDER, DEFAULT_GENDER),
    }]


def active_profile(entry: Any) -> dict[str, Any]:
    """Return the selected profile, falling back to the first after deletion."""
    profiles = get_profiles(entry)
    selected = entry.options.get(CONF_ACTIVE_PROFILE)
    return next(
        (profile for profile in profiles if profile[CONF_PROFILE_NAME] == selected),
        profiles[0],
    )


def profile_options(
    profiles: list[dict[str, Any]], selected_name: str
) -> dict[str, Any]:
    """Build fresh options so config-entry update detection always sees a change."""
    return {
        CONF_PROFILES: [dict(profile) for profile in profiles],
        CONF_ACTIVE_PROFILE: selected_name,
    }
