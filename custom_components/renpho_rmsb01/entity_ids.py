"""Stable entity unique IDs and one-time migration for the 0.4.0 ID regression."""

import logging
from typing import Any

from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ADDRESS,
    CONF_PROFILE_ID,
    DOMAIN,
)
from .profiles import get_profiles

_LOGGER = logging.getLogger(__name__)


def unique_id_address(entry: Any) -> str:
    """Keep the pre-0.4.0 convention: uppercase MAC without separators."""
    return entry.data[CONF_ADDRESS].upper().replace(":", "")


def entity_unique_id(entry: Any, suffix: str) -> str:
    """Build an entity ID that is independent of coordinator address formatting."""
    return f"{unique_id_address(entry)}_{suffix}"


def migrate_entity_unique_ids(hass: Any, entry: Any) -> dict[str, int]:
    """Repair colon-form IDs created by 0.4.0 before entity platforms load.

    A pre-existing separator-free entity wins so its original entity ID and
    history remain attached. Otherwise the colon-form registry entry is
    renamed in place, preserving the entity ID and any restored state.
    """
    old_prefix = entry.data[CONF_ADDRESS].upper()
    new_prefix = unique_id_address(entry)
    counts = {"migrated": 0, "duplicates_removed": 0}
    if old_prefix == new_prefix:
        return counts

    from .sensor import SENSORS  # Platform modules are safe to import during setup.

    suffixes = [("select", "active_profile"), ("select", "viewed_profile")]
    suffixes.extend(("sensor", description.key) for description in SENSORS)
    for profile in get_profiles(entry):
        suffixes.extend(
            ("sensor", f"{profile[CONF_PROFILE_ID]}_{description.key}")
            for description in SENSORS
        )

    registry = er.async_get(hass)
    for platform, suffix in suffixes:
        canonical_id = f"{new_prefix}_{suffix}"
        colon_id = f"{old_prefix}_{suffix}"
        colon_entity_id = registry.async_get_entity_id(platform, DOMAIN, colon_id)
        if colon_entity_id is None:
            continue
        canonical_entity_id = registry.async_get_entity_id(
            platform, DOMAIN, canonical_id
        )
        if canonical_entity_id is not None:
            registry.async_remove(colon_entity_id)
            counts["duplicates_removed"] += 1
            _LOGGER.info("Removed duplicate R-MSB01 registry entity %s", colon_entity_id)
        else:
            registry.async_update_entity(colon_entity_id, new_unique_id=canonical_id)
            counts["migrated"] += 1
            _LOGGER.info("Migrated R-MSB01 registry entity %s", colon_entity_id)
    return counts
