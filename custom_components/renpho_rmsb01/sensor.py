"""Sensors for completed R-MSB01 measurements."""

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfMass
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ADDRESS, DOMAIN, MODEL

SENSORS = (
    SensorEntityDescription(
        key="weight_kg", name="Weight", native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        device_class=SensorDeviceClass.WEIGHT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2, icon="mdi:scale-bathroom",
    ),
    SensorEntityDescription(
        key="bmi", name="BMI", native_unit_of_measurement="kg/m²",
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:human",
    ),
    SensorEntityDescription(
        key="bodyfat_percent", name="Body fat", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:percent",
    ),
    SensorEntityDescription(
        key="subfat_percent", name="Subcutaneous fat", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:percent",
    ),
    SensorEntityDescription(
        key="visceral_fat", name="Visceral fat", state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:stomach",
    ),
    SensorEntityDescription(
        key="water_percent", name="Body water", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:water-percent",
    ),
    SensorEntityDescription(
        key="muscle_percent", name="Muscle percentage", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:percent",
    ),
    SensorEntityDescription(
        key="bone_kg", name="Bone mass", native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        device_class=SensorDeviceClass.WEIGHT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2, icon="mdi:bone",
    ),
    SensorEntityDescription(
        key="bmr_kcal", name="Basal metabolic rate", native_unit_of_measurement="kcal",
        state_class=SensorStateClass.MEASUREMENT, icon="mdi:fire",
    ),
    SensorEntityDescription(
        key="protein_percent", name="Protein", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:percent",
    ),
    SensorEntityDescription(
        key="lean_body_mass_kg", name="Lean body mass", native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        device_class=SensorDeviceClass.WEIGHT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2, icon="mdi:human-handsdown",
    ),
    SensorEntityDescription(
        key="muscle_mass_kg", name="Muscle mass", native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        device_class=SensorDeviceClass.WEIGHT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2, icon="mdi:arm-flex",
    ),
    SensorEntityDescription(
        key="body_age_years", name="Body age", native_unit_of_measurement="years",
        state_class=SensorStateClass.MEASUREMENT, icon="mdi:account-clock",
    ),
    SensorEntityDescription(
        key="measured_at", name="Last measurement", device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check",
    ),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Create all supported metric entities."""
    async_add_entities(
        RenphoSensor(entry.runtime_data, entry, description) for description in SENSORS
    )


class RenphoSensor(CoordinatorEntity, SensorEntity):
    """One value from the latest completed measurement."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, description: SensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        address = entry.data[CONF_ADDRESS].upper()
        self._attr_unique_id = f"{address.replace(':', '')}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "connections": {(dr.CONNECTION_BLUETOOTH, address)},
            "name": entry.title,
            "manufacturer": "Renpho",
            "model": MODEL,
        }

    @property
    def available(self) -> bool:
        """Keep the last completed values visible while the scale sleeps."""
        if self.coordinator.data is None:
            return False
        if self.entity_description.key == "measured_at":
            return True
        return self.entity_description.key in self.coordinator.data["metrics"]

    @property
    def native_value(self):
        """Return the current metric or timestamp."""
        if not self.available:
            return None
        if self.entity_description.key == "measured_at":
            return datetime.fromisoformat(self.coordinator.data["measured_at"])
        return self.coordinator.data["metrics"][self.entity_description.key]

    @property
    def extra_state_attributes(self):
        """Expose protocol diagnostics without creating unitless impedance sensors."""
        if not self.available:
            return None
        data = self.coordinator.data
        if self.entity_description.key == "weight_kg":
            return {
                "resistance_50_raw": data["metrics"]["resistance_50_raw"],
                "resistance_500_raw": data["metrics"]["resistance_500_raw"],
                "user_index": data["metadata"]["user_index"],
                "profile": data.get("profile"),
            }
        if self.entity_description.key == "measured_at":
            return {
                "capabilities": data["capabilities"],
                "raw_packets": data["raw_packets"],
                "decoded_but_masked_out": data["masked_out"],
            }
        return None
