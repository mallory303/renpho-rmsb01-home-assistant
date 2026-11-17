"""Shared latest-measurement sensors and stable per-person sensor sets."""

import logging
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfMass, UnitOfTime
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ADDRESS,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_SCALE_USER_INDEX,
    DOMAIN,
    MODEL,
)
from .entity_ids import entity_unique_id
from .profiles import get_profiles

_LOGGER = logging.getLogger(__name__)

SENSORS = (
    SensorEntityDescription(
        key="weight_kg", name="Weight", native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        device_class=SensorDeviceClass.WEIGHT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="bmi", name="BMI", native_unit_of_measurement="kg/m²",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="bodyfat_percent", name="Body fat", native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="subfat_percent", name="Subcutaneous fat", native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="visceral_fat", name="Visceral fat",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="water_percent", name="Body water", native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="muscle_percent", name="Muscle percentage", native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="bone_kg", name="Bone mass", native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        device_class=SensorDeviceClass.WEIGHT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="bmr_kcal", name="Basal metabolic rate", native_unit_of_measurement="kcal",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="protein_percent", name="Protein", native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="lean_body_mass_kg", name="Lean body mass", native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        device_class=SensorDeviceClass.WEIGHT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="muscle_mass_kg", name="Muscle mass", native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        device_class=SensorDeviceClass.WEIGHT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="body_age_years", name="Body age", native_unit_of_measurement=UnitOfTime.YEARS,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="measured_at", name="Last measurement", device_class=SensorDeviceClass.TIMESTAMP,
    ),
)

CARD_SENSOR_KEYS = {
    "weight_kg": "weight",
    "bmi": "bmi",
    "bodyfat_percent": "body_fat",
    "subfat_percent": "subcutaneous_fat",
    "visceral_fat": "visceral_fat",
    "water_percent": "body_water",
    "muscle_percent": "muscle_percentage",
    "bone_kg": "bone_mass",
    "bmr_kcal": "basal_metabolic_rate",
    "protein_percent": "protein",
    "lean_body_mass_kg": "lean_body_mass",
    "muscle_mass_kg": "muscle_mass",
    "body_age_years": "body_age",
    "measured_at": "last_measurement",
}


def _device_info(entry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        connections={(CONNECTION_BLUETOOTH, entry.data[CONF_ADDRESS])},
        manufacturer="Renpho", model=MODEL, name=entry.title,
    )


def _value(data: dict[str, Any], key: str):
    if key == "measured_at":
        return datetime.fromisoformat(data["measured_at"])
    return data["metrics"][key]


def _measurement_attributes(data: dict[str, Any], detailed: bool) -> dict[str, Any]:
    attributes = {
        "profile": data.get("profile"),
        "profile_id": data.get("profile_id"),
        "identified": data.get("identified", True),
        "user_index": data["metadata"].get("user_index"),
        "measured_at": data["measured_at"],
    }
    if detailed:
        attributes.update({
            "capabilities": data["capabilities"],
            "raw_resistance_50": data["metrics"].get("resistance_50_raw"),
            "raw_resistance_500": data["metrics"].get("resistance_500_raw"),
        })
    return attributes


def _with_previous_value(
    attributes: dict[str, Any], previous: dict[str, Any] | None, key: str
) -> dict[str, Any]:
    """Add the preceding completed value without mixing profiles or sessions."""
    if previous is None:
        return attributes
    if key == "measured_at":
        previous_value = previous["measured_at"]
    else:
        previous_value = previous["metrics"].get(key)
    if previous_value is not None:
        attributes["previous_value"] = previous_value
        attributes["previous_measured_at"] = previous["measured_at"]
    return attributes


def _previous_from_states(states: list[Any], current_measured_at: str):
    """Find the latest distinct recorded measurement, ignoring restart copies."""
    for state in reversed(states):
        if state.state in ("unknown", "unavailable"):
            continue
        measured_at = state.attributes.get("measured_at")
        if not measured_at or measured_at == current_measured_at:
            continue
        try:
            return float(state.state), measured_at
        except (TypeError, ValueError):
            continue
    return None


async def _async_previous_from_history(hass, entity_id: str, current_measured_at: str):
    """Recover an upgrade baseline from this entity's own recorder history."""
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states

        start_time = datetime.fromisoformat(current_measured_at) - timedelta(days=365)
        history = await get_instance(hass).async_add_executor_job(
            partial(
                get_significant_states,
                hass,
                start_time,
                entity_ids=[entity_id],
                include_start_time_state=False,
                significant_changes_only=False,
            )
        )
    except Exception:
        _LOGGER.debug(
            "Could not recover previous value for %s from recorder history",
            entity_id,
            exc_info=True,
        )
        return None
    return _previous_from_states(history.get(entity_id, []), current_measured_at)


class RenphoSensor(CoordinatorEntity, SensorEntity):
    """Backward-compatible latest-measurement sensor, including unassigned users."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = entity_unique_id(coordinator.entry, description.key)
        self._attr_device_info = _device_info(coordinator.entry)

    @property
    def available(self) -> bool:
        """Keep completed values visible without depending on poll success state."""
        if self.coordinator.data is None:
            return False
        if self.entity_description.key == "measured_at":
            return True
        return self.entity_description.key in self.coordinator.data["metrics"]

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return _value(self.coordinator.data, self.entity_description.key)

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return None
        data = self.coordinator.data
        return _with_previous_value(
            _measurement_attributes(
                data, self.entity_description.key in ("weight_kg", "measured_at")
            ),
            self.coordinator.previous_data,
            self.entity_description.key,
        )


class RenphoProfileSensor(CoordinatorEntity, RestoreSensor):
    """One person's independently restored and recorded measurement sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, profile: dict[str, Any], description) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.profile = profile
        self.entity_description = description
        self._profile_id = profile[CONF_PROFILE_ID]
        self._attr_name = f"{profile[CONF_PROFILE_NAME]} {description.name}"
        self._attr_unique_id = entity_unique_id(
            coordinator.entry, f"{self._profile_id}_{description.key}"
        )
        self._attr_device_info = _device_info(coordinator.entry)
        self._restored_value = None
        self._restored_attributes: dict[str, Any] = {}

    @property
    def _data(self) -> dict[str, Any] | None:
        return self.coordinator.profile_measurements.get(self._profile_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._data is not None:
            return
        restored = await self.async_get_last_sensor_data()
        if restored is not None:
            self._restored_value = restored.native_value
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._restored_attributes = {
                key: value
                for key, value in last_state.attributes.items()
                if key in (
                    "profile", "profile_id", "identified", "user_index", "measured_at",
                    "previous_value", "previous_measured_at",
                )
            }
        if (
            self.entity_description.key != "measured_at"
            and self._restored_value is not None
            and self._restored_attributes.get("previous_value") is None
            and self._restored_attributes.get("measured_at") is not None
        ):
            previous = await _async_previous_from_history(
                self.hass,
                self.entity_id,
                self._restored_attributes["measured_at"],
            )
            if previous is not None and self._data is None:
                self._restored_attributes["previous_value"] = previous[0]
                self._restored_attributes["previous_measured_at"] = previous[1]

    @property
    def available(self) -> bool:
        return self._data is not None or self._restored_value is not None

    @property
    def native_value(self):
        data = self._data
        if data is None:
            return self._restored_value
        return _value(data, self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._data
        if data is None:
            return dict(self._restored_attributes)
        attributes = _measurement_attributes(
            data, self.entity_description.key in ("weight_kg", "measured_at")
        )
        if CONF_SCALE_USER_INDEX in self.profile:
            attributes["scale_user_index"] = self.profile[CONF_SCALE_USER_INDEX]
        previous = self.coordinator.previous_profile_measurements.get(self._profile_id)
        if previous is not None:
            return _with_previous_value(attributes, previous, self.entity_description.key)
        if self._restored_value is not None:
            # After a restart, the first live measurement compares with the value
            # that was current before that restart, not with its older predecessor.
            previous_value = self._restored_value
            if isinstance(previous_value, datetime):
                previous_value = previous_value.isoformat()
            attributes["previous_value"] = previous_value
            restored_at = self._restored_attributes.get("measured_at")
            if restored_at is not None:
                attributes["previous_measured_at"] = restored_at
        return attributes


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = [RenphoSensor(coordinator, description) for description in SENSORS]
    for profile in get_profiles(entry):
        entities.extend(
            RenphoProfileSensor(coordinator, profile, description) for description in SENSORS
        )
    async_add_entities(entities)
