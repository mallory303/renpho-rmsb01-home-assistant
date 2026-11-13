"""Coordinator attribution and enrollment safety tests with synthetic scale data."""

import asyncio
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from bleak import BleakError

from tests.helpers import load_module


def load_coordinator():
    root = ModuleType("homeassistant")
    root.__path__ = []
    components = ModuleType("homeassistant.components")
    components.__path__ = []
    bluetooth = ModuleType("homeassistant.components.bluetooth")
    bluetooth.__path__ = []
    bluetooth.BluetoothScanningMode = SimpleNamespace(ACTIVE="active")
    bluetooth.async_ble_device_from_address = lambda *args, **kwargs: object()
    bluetooth.async_clear_advertisement_history = lambda *args: None
    active = ModuleType("homeassistant.components.bluetooth.active_update_coordinator")
    active.ActiveBluetoothDataUpdateCoordinator = type("ActiveCoordinator", (), {})
    config_entries = ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = object
    retry = ModuleType("bleak_retry_connector")
    retry.establish_connection = object()  # Never called by these synthetic coordinator tests.
    modules = {
        "bleak_retry_connector": retry,
        "homeassistant": root,
        "homeassistant.components": components,
        "homeassistant.components.bluetooth": bluetooth,
        "homeassistant.components.bluetooth.active_update_coordinator": active,
        "homeassistant.config_entries": config_entries,
        "homeassistant.core": core,
    }
    with patch.dict(sys.modules, modules):
        return load_module("coordinator")


coordinator_module = load_coordinator()
RenphoCoordinator = coordinator_module.RenphoCoordinator


def profile(name="User A", profile_id="profile-a", **extra):
    return {
        "profile_name": name,
        "profile_id": profile_id,
        "age": 30,
        "height": 170,
        "gender": "male",
        **extra,
    }


def entry_for(profiles, selected="Auto"):
    return SimpleNamespace(
        entry_id="synthetic-entry",
        title="Synthetic scale",
        data={"address": "02:00:00:00:00:00"},
        options={"profiles": profiles, "active_profile": selected},
    )


def bare_coordinator(entry):
    coordinator = object.__new__(RenphoCoordinator)
    coordinator.entry = entry
    coordinator.address = entry.data["address"]
    coordinator.hass = SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: None))
    coordinator.profile_measurements = {}
    coordinator._session_lock = asyncio.Lock()
    coordinator._admin = None
    coordinator._last_attempt = 0
    return coordinator


def scale_user(index, key, source=None):
    source = source or profile()
    return {
        "user_index": index,
        "user_key": key,
        "age": source["age"],
        "height": source["height"],
        "gender": source["gender"],
        "algorithm": 5,
        "last_weight_kg": 70.0,
    }


def measurement(index):
    return {
        "metadata": {"user_index": index},
        "metrics": {"weight_kg": 70.0, "bmi": 22.0, "bodyfat_percent": 20.0},
        "measured_at": "2026-01-01T00:00:00+00:00",
    }


class AttributionTest(unittest.TestCase):
    def test_known_auto_slot_updates_only_mapped_person(self):
        first = profile()
        second = profile("User B", "profile-b")
        coordinator = bare_coordinator(entry_for([first, second]))
        result = measurement(2)
        first["scale_user_index"] = 2
        first["scale_user_key"] = 111
        coordinator._classify_result(result, True)
        self.assertTrue(result["identified"])
        self.assertEqual(result["profile"], "User A")
        self.assertEqual(list(coordinator.profile_measurements), ["profile-a"])

    def test_unknown_auto_slot_changes_no_person_history(self):
        known = profile(scale_user_index=2, scale_user_key=111)
        coordinator = bare_coordinator(entry_for([known]))
        known_result = measurement(2)
        coordinator._classify_result(known_result, True)
        unknown = measurement(7)
        coordinator._classify_result(unknown, True)
        self.assertFalse(unknown["identified"])
        self.assertIsNone(unknown["profile"])
        self.assertEqual(coordinator.profile_measurements["profile-a"], known_result)
        self.assertEqual(len(coordinator.profile_measurements), 1)

    def test_manual_visitor_still_updates_selected_person(self):
        first = profile()
        second = profile("User B", "profile-b")
        coordinator = bare_coordinator(entry_for([first, second], "User B"))
        result = measurement(254)
        coordinator._classify_result(result, False)
        self.assertEqual(result["profile"], "User B")
        self.assertEqual(list(coordinator.profile_measurements), ["profile-b"])


class EnrollmentTest(unittest.IsolatedAsyncioTestCase):
    async def run_enrollment(self, configured, users):
        coordinator = bare_coordinator(entry_for([configured]))
        calls = []

        async def fake_admin(operation, device, value=None):
            calls.append((operation, dict(value) if value else None))
            if operation == "read":
                return users
            if operation == "register":
                return {"user_index": 3, "user_key": value["scale_user_key"]}
            return {"user_index": value["scale_user_index"], "user_key": value["scale_user_key"]}

        with (
            patch.object(coordinator, "_run_admin", fake_admin),
            patch.object(coordinator_module.bluetooth, "async_clear_advertisement_history"),
        ):
            result = await coordinator.async_register_profile(configured)
        return result, calls

    async def test_unassigned_profile_reads_then_registers_free_slot(self):
        result, calls = await self.run_enrollment(profile(), [scale_user(1, 111)])
        self.assertEqual(result["scale_user_index"], 3)
        self.assertNotIn(result["scale_user_key"], (0, 111, 0xFFEE))
        self.assertEqual([call[0] for call in calls], ["read", "register"])
        self.assertNotIn("scale_user_index", calls[1][1])

    async def test_full_scale_stops_after_read(self):
        users = [scale_user(index, 1000 + index) for index in range(1, 9)]
        with self.assertRaisesRegex(BleakError, "eight"):
            await self.run_enrollment(profile(), users)

    async def test_stale_mapping_never_overwrites_slot(self):
        configured = profile(scale_user_index=2, scale_user_key=222)
        with self.assertRaisesRegex(BleakError, "does not match"):
            await self.run_enrollment(configured, [scale_user(2, 333)])

    async def test_existing_mapping_syncs_only_when_demographics_changed(self):
        configured = profile(
            scale_user_index=2,
            scale_user_key=222,
            scale_profile={"age": 29, "height": 170, "gender": "male"},
        )
        result, calls = await self.run_enrollment(
            configured, [scale_user(2, 222, configured)]
        )
        self.assertEqual(result["scale_user_index"], 2)
        self.assertEqual([call[0] for call in calls], ["read", "sync"])

    async def test_exact_key_and_demographic_recovery_requires_no_write(self):
        configured = profile()
        coordinator = bare_coordinator(entry_for([configured]))
        key = coordinator._new_user_key(configured, set())
        result, calls = await self.run_enrollment(
            configured, [scale_user(4, key, configured)]
        )
        self.assertEqual(result, {"scale_user_index": 4, "scale_user_key": key})
        self.assertEqual([call[0] for call in calls], ["read"])


if __name__ == "__main__":
    unittest.main()
