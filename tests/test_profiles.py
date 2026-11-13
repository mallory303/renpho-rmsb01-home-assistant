"""Tests for HA-side profile migration and active-user selection."""

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from tests.helpers import load_module

profiles_module = load_module("profiles")


def make_entry(data=None, options=None):
    return SimpleNamespace(
        data=data or {"age": 30, "height": 170, "gender": "male"},
        options=options or {},
        title="Synthetic scale",
    )


def load_select_module():
    root = ModuleType("homeassistant")
    root.__path__ = []
    components = ModuleType("homeassistant.components")
    components.__path__ = []
    select_module = ModuleType("homeassistant.components.select")
    select_module.SelectEntity = type("SelectEntity", (), {})
    exceptions = ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    helpers = ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    registry = ModuleType("homeassistant.helpers.device_registry")
    registry.CONNECTION_BLUETOOTH = "bluetooth"
    helpers.device_registry = registry
    root.components = components
    root.helpers = helpers
    components.select = select_module
    modules = {
        "homeassistant": root,
        "homeassistant.components": components,
        "homeassistant.components.select": select_module,
        "homeassistant.exceptions": exceptions,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.device_registry": registry,
    }
    with patch.dict(sys.modules, modules):
        return load_module("select")


class ProfilesTest(unittest.TestCase):
    def test_legacy_single_profile_is_preserved(self):
        entry = make_entry(data={
            "profile_name": "User A", "age": 41, "height": 181, "gender": "female",
        })
        self.assertEqual(profiles_module.get_profiles(entry), [{
            "profile_name": "User A", "age": 41, "height": 181, "gender": "female",
        }])
        self.assertEqual(profiles_module.active_profile(entry)["profile_name"], "User A")

    def test_multiple_profiles_selection_fallback_and_copies(self):
        configured = [
            {"profile_name": "User A", "age": 30, "height": 170, "gender": "male"},
            {"profile_name": "User B", "age": 35, "height": 165, "gender": "female"},
        ]
        entry = make_entry(options={"profiles": configured, "active_profile": "User B"})
        returned = profiles_module.get_profiles(entry)
        returned[0]["profile_name"] = "Changed"
        self.assertEqual(configured[0]["profile_name"], "User A")
        self.assertEqual(profiles_module.active_profile(entry)["profile_name"], "User B")
        entry.options["active_profile"] = "Missing"
        self.assertEqual(profiles_module.active_profile(entry)["profile_name"], "User A")


class SelectEntityTest(unittest.IsolatedAsyncioTestCase):
    async def test_select_updates_only_ha_profile_options(self):
        select_module = load_select_module()
        entry = make_entry(
            data={"address": "AA:BB:CC:DD:EE:FF"},
            options={
                "profiles": [
                    {"profile_name": "User A", "age": 30, "height": 170, "gender": "male"},
                    {"profile_name": "User B", "age": 35, "height": 165, "gender": "female"},
                ],
                "active_profile": "User A",
            },
        )
        calls = []

        def update_entry(updated_entry, options):
            self.assertIs(updated_entry, entry)
            entry.options = options
            calls.append(options)

        entity = select_module.RenphoUserSelect(entry)
        entity.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=update_entry)
        )
        self.assertEqual(entity.options, ["User A", "User B"])
        self.assertEqual(entity.current_option, "User A")
        await entity.async_select_option("User B")
        self.assertEqual(entity.current_option, "User B")
        self.assertEqual(entry.data, {"address": "AA:BB:CC:DD:EE:FF"})
        self.assertEqual(len(calls), 1)
        with self.assertRaises(select_module.HomeAssistantError):
            await entity.async_select_option("Unknown")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
