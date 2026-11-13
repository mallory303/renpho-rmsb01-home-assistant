"""Regression tests for the 0.4.0 colon-form entity unique-ID migration."""

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from tests.helpers import PACKAGE_NAME, load_module


def load_entity_ids_module():
    root = ModuleType("homeassistant")
    root.__path__ = []
    helpers = ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    registry = ModuleType("homeassistant.helpers.entity_registry")
    registry.async_get = lambda hass: hass.entity_registry
    root.helpers = helpers
    helpers.entity_registry = registry
    with patch.dict(sys.modules, {
        "homeassistant": root,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.entity_registry": registry,
    }):
        return load_module("entity_ids")


entity_ids = load_entity_ids_module()


class FakeRegistry:
    def __init__(self, entries):
        self.entries = {
            (platform, unique_id): entity_id
            for platform, unique_id, entity_id in entries
        }

    def async_get_entity_id(self, platform, domain, unique_id):
        assert domain == "renpho_rmsb01"
        return self.entries.get((platform, unique_id))

    def async_update_entity(self, entity_id, *, new_unique_id):
        key = next(key for key, value in self.entries.items() if value == entity_id)
        del self.entries[key]
        self.entries[(key[0], new_unique_id)] = entity_id

    def async_remove(self, entity_id):
        key = next(key for key, value in self.entries.items() if value == entity_id)
        del self.entries[key]


class EntityUniqueIdMigrationTest(unittest.TestCase):
    def test_legacy_ids_and_migration_preserve_original_entities(self):
        entry = SimpleNamespace(
            data={"address": "02:00:00:00:00:00"},
            options={
                "profiles": [{
                    "profile_name": "User A", "profile_id": "profile-a",
                    "age": 30, "height": 170, "gender": "male",
                }],
                "active_profile": "User A",
            },
        )
        registry = FakeRegistry([
            ("sensor", "020000000000_weight_kg", "sensor.original_weight"),
            ("sensor", "02:00:00:00:00:00_weight_kg", "sensor.duplicate_weight"),
            ("select", "020000000000_active_profile", "select.original_user"),
            ("select", "02:00:00:00:00:00_active_profile", "select.duplicate_user"),
            ("select", "02:00:00:00:00:00_viewed_profile", "select.viewed_user"),
            (
                "sensor",
                "02:00:00:00:00:00_profile-a_weight_kg",
                "sensor.user_a_weight",
            ),
        ])
        fake_sensor = ModuleType(f"{PACKAGE_NAME}.sensor")
        fake_sensor.SENSORS = (SimpleNamespace(key="weight_kg"),)
        with patch.dict(sys.modules, {f"{PACKAGE_NAME}.sensor": fake_sensor}):
            counts = entity_ids.migrate_entity_unique_ids(
                SimpleNamespace(entity_registry=registry), entry
            )

        self.assertEqual(counts, {"migrated": 2, "duplicates_removed": 2})
        self.assertEqual(
            registry.entries[("sensor", "020000000000_weight_kg")],
            "sensor.original_weight",
        )
        self.assertEqual(
            registry.entries[("select", "020000000000_active_profile")],
            "select.original_user",
        )
        self.assertEqual(
            registry.entries[("select", "020000000000_viewed_profile")],
            "select.viewed_user",
        )
        self.assertEqual(
            registry.entries[("sensor", "020000000000_profile-a_weight_kg")],
            "sensor.user_a_weight",
        )
        self.assertNotIn(
            ("sensor", "02:00:00:00:00:00_weight_kg"), registry.entries
        )
        self.assertNotIn(
            ("select", "02:00:00:00:00:00_active_profile"), registry.entries
        )

    def test_separator_free_address_is_a_noop(self):
        entry = SimpleNamespace(
            data={"address": "020000000000"}, options={"profiles": []}
        )
        self.assertEqual(
            entity_ids.migrate_entity_unique_ids(None, entry),
            {"migrated": 0, "duplicates_removed": 0},
        )


if __name__ == "__main__":
    unittest.main()
