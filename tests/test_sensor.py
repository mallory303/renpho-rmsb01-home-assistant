"""Synthetic per-profile sensor identity, attribution, and restoration tests."""

import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from tests.helpers import load_module


def load_sensor():
    root = ModuleType("homeassistant")
    root.__path__ = []
    components = ModuleType("homeassistant.components")
    components.__path__ = []
    sensor = ModuleType("homeassistant.components.sensor")

    class Description:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class SensorEntity:
        pass

    class RestoreSensor(SensorEntity):
        pass

    sensor.RestoreSensor = RestoreSensor
    sensor.SensorEntity = SensorEntity
    sensor.SensorEntityDescription = Description
    sensor.SensorDeviceClass = SimpleNamespace(WEIGHT="weight", TIMESTAMP="timestamp")
    sensor.SensorStateClass = SimpleNamespace(MEASUREMENT="measurement")
    const = ModuleType("homeassistant.const")
    const.UnitOfMass = SimpleNamespace(KILOGRAMS="kg")
    const.UnitOfTime = SimpleNamespace(YEARS="years")
    helpers = ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    device = ModuleType("homeassistant.helpers.device_registry")
    device.CONNECTION_BLUETOOTH = "bluetooth"
    device.DeviceInfo = lambda **kwargs: kwargs
    entity_registry = ModuleType("homeassistant.helpers.entity_registry")
    entity_registry.async_get = lambda hass: None
    update = ModuleType("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

        @property
        def available(self):
            return self.coordinator.last_update_success

        async def async_added_to_hass(self):
            return None

    update.CoordinatorEntity = CoordinatorEntity
    modules = {
        "homeassistant": root,
        "homeassistant.components": components,
        "homeassistant.components.sensor": sensor,
        "homeassistant.const": const,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.device_registry": device,
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.helpers.update_coordinator": update,
    }
    with patch.dict(sys.modules, modules):
        return load_module("sensor")


sensor_module = load_sensor()


def make_entry():
    coordinator = SimpleNamespace(
        address="02:00:00:00:00:00",
        data=None,
        previous_data=None,
        profile_measurements={},
        previous_profile_measurements={},
    )
    profiles = [
        {"profile_name": "User A", "profile_id": "profile-a", "age": 30, "height": 170, "gender": "male", "scale_user_index": 2},
        {"profile_name": "User B", "profile_id": "profile-b", "age": 35, "height": 165, "gender": "female"},
    ]
    entry = SimpleNamespace(
        entry_id="synthetic-entry",
        title="Synthetic scale",
        data={"address": coordinator.address},
        options={"profiles": profiles, "active_profile": "Auto"},
        runtime_data=coordinator,
    )
    coordinator.entry = entry
    return entry, coordinator


def measurement(profile_id, user_index, weight=70.0):
    return {
        "profile": "User A",
        "profile_id": profile_id,
        "identified": True,
        "measured_at": "2026-01-01T00:00:00+00:00",
        "metadata": {"user_index": user_index},
        "capabilities": {},
        "metrics": {"weight_kg": weight},
    }


class ProfileSensorTest(unittest.IsolatedAsyncioTestCase):
    async def test_shared_sensor_availability_does_not_require_coordinator_success_flag(self):
        _, coordinator = make_entry()
        entity = sensor_module.RenphoSensor(coordinator, sensor_module.SENSORS[0])
        self.assertFalse(entity.available)
        coordinator.data = measurement("profile-a", 254, 70.5)
        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value, 70.5)

    async def test_shared_ids_stay_compatible_and_profiles_are_distinct(self):
        entry, _ = make_entry()
        entities = []
        await sensor_module.async_setup_entry(None, entry, entities.extend)
        self.assertEqual(len(entities), 42)
        self.assertEqual(len({entity._attr_unique_id for entity in entities}), 42)
        shared = entities[:14]
        self.assertEqual(shared[0]._attr_unique_id, "020000000000_weight_kg")
        profile_weight_ids = {
            entities[14]._attr_unique_id,
            entities[28]._attr_unique_id,
        }
        self.assertEqual(
            profile_weight_ids,
            {
                "020000000000_profile-a_weight_kg",
                "020000000000_profile-b_weight_kg",
            },
        )

    async def test_only_mapped_profile_reads_new_measurement(self):
        entry, coordinator = make_entry()
        first = sensor_module.RenphoProfileSensor(
            coordinator, entry.options["profiles"][0], sensor_module.SENSORS[0]
        )
        second = sensor_module.RenphoProfileSensor(
            coordinator, entry.options["profiles"][1], sensor_module.SENSORS[0]
        )
        coordinator.profile_measurements["profile-a"] = measurement("profile-a", 2, 71.25)
        self.assertTrue(first.available)
        self.assertEqual(first.native_value, 71.25)
        self.assertEqual(first.extra_state_attributes["scale_user_index"], 2)
        self.assertFalse(second.available)
        self.assertIsNone(second.native_value)

    async def test_person_sensor_restores_then_live_value_replaces_restore(self):
        entry, coordinator = make_entry()
        entity = sensor_module.RenphoProfileSensor(
            coordinator, entry.options["profiles"][0], sensor_module.SENSORS[0]
        )

        async def restored_value():
            return SimpleNamespace(native_value=68.5)

        async def restored_state():
            return SimpleNamespace(attributes={
                "profile": "User A", "profile_id": "profile-a", "identified": True,
                "user_index": 2, "measured_at": "2025-12-31T00:00:00+00:00",
            })

        entity.async_get_last_sensor_data = restored_value
        entity.async_get_last_state = restored_state
        await entity.async_added_to_hass()
        self.assertTrue(entity.available)
        self.assertEqual(entity.native_value, 68.5)
        self.assertEqual(entity.extra_state_attributes["profile_id"], "profile-a")
        coordinator.profile_measurements["profile-a"] = measurement("profile-a", 2, 72.0)
        self.assertEqual(entity.native_value, 72.0)
        self.assertEqual(entity.extra_state_attributes["user_index"], 2)
        self.assertEqual(entity.extra_state_attributes["previous_value"], 68.5)
        self.assertEqual(
            entity.extra_state_attributes["previous_measured_at"],
            "2025-12-31T00:00:00+00:00",
        )

    async def test_shared_and_profile_sensors_expose_their_own_previous_value(self):
        entry, coordinator = make_entry()
        previous = measurement("profile-a", 2, 71.0)
        current = measurement("profile-a", 2, 69.5)
        current["measured_at"] = "2026-01-02T00:00:00+00:00"
        coordinator.previous_data = previous
        coordinator.data = current
        coordinator.previous_profile_measurements["profile-a"] = previous
        coordinator.profile_measurements["profile-a"] = current

        shared = sensor_module.RenphoSensor(coordinator, sensor_module.SENSORS[0])
        person = sensor_module.RenphoProfileSensor(
            coordinator, entry.options["profiles"][0], sensor_module.SENSORS[0]
        )
        for entity in (shared, person):
            attributes = entity.extra_state_attributes
            self.assertEqual(attributes["previous_value"], 71.0)
            self.assertEqual(attributes["previous_measured_at"], previous["measured_at"])

    async def test_first_live_value_after_restart_compares_with_restored_current(self):
        entry, coordinator = make_entry()
        entity = sensor_module.RenphoProfileSensor(
            coordinator, entry.options["profiles"][0], sensor_module.SENSORS[0]
        )

        async def restored_value():
            return SimpleNamespace(native_value=68.5)

        async def restored_state():
            return SimpleNamespace(attributes={
                "profile": "User A", "profile_id": "profile-a", "identified": True,
                "user_index": 2, "measured_at": "2025-12-31T00:00:00+00:00",
                "previous_value": 69.0,
                "previous_measured_at": "2025-12-30T00:00:00+00:00",
            })

        entity.async_get_last_sensor_data = restored_value
        entity.async_get_last_state = restored_state
        await entity.async_added_to_hass()
        self.assertEqual(entity.extra_state_attributes["previous_value"], 69.0)

        coordinator.profile_measurements["profile-a"] = measurement("profile-a", 2, 68.0)
        self.assertEqual(entity.native_value, 68.0)
        attributes = entity.extra_state_attributes
        self.assertEqual(attributes["previous_value"], 68.5)
        self.assertEqual(
            attributes["previous_measured_at"], "2025-12-31T00:00:00+00:00"
        )


if __name__ == "__main__":
    unittest.main()
