"""Status and diagnostics sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller import WoodController
from .readings import evaluate_group


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([StatusSensor(controller, entry), OpeningSensor(controller, entry)])


class _Base(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: WoodController, entry: ConfigEntry, key: str) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name="Wood Stove Mode"
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._controller.async_add_listener(self.async_write_ha_state)
        )


class StatusSensor(_Base):
    _attr_name = "Status"
    _attr_icon = "mdi:fireplace"

    def __init__(self, controller: WoodController, entry: ConfigEntry) -> None:
        super().__init__(controller, entry, "status")

    @property
    def native_value(self) -> str:
        state = self._controller.engine.state
        if state.emergency:
            return "emergency"
        if state.exchanger_failsafe:
            return "failsafe"
        return state.mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._controller.engine.state
        attrs: dict[str, Any] = {
            "valve_opening": state.last_opening,
            "control_source": state.pid_source,
            "sensor_faults": list(state.faults),
        }
        inputs = self._controller.last_inputs
        if inputs is not None:
            for name, readings in (
                ("stove_temperature", inputs.stove),
                ("exchanger_temperature", inputs.exchanger),
                ("system_water_temperature", inputs.water),
            ):
                attrs[name] = evaluate_group(readings).value
        return attrs


class OpeningSensor(_Base):
    _attr_name = "Valve opening"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:valve"

    def __init__(self, controller: WoodController, entry: ConfigEntry) -> None:
        super().__init__(controller, entry, "opening")

    @property
    def native_value(self) -> float | None:
        state = self._controller.engine.state
        return state.last_opening if state.mode != "boiler" else None
