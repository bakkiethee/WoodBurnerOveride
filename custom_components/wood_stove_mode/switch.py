"""The manual wood-mode switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller import WoodController


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([WoodModeSwitch(hass.data[DOMAIN][entry.entry_id], entry)])


class WoodModeSwitch(SwitchEntity):
    """On starts wood mode. Off ends it, but only when the stove sensor is below 60 °C.

    The switch also mirrors the mode, so it shows on while wood mode runs.
    """

    _attr_has_entity_name = True
    _attr_name = "Wood mode"
    _attr_should_poll = False
    _attr_icon = "mdi:fireplace"

    def __init__(self, controller: WoodController, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_manual"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name="Wood Stove Mode"
        )

    @property
    def is_on(self) -> bool:
        return self._controller.manual_on

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._controller.async_add_listener(self.async_write_ha_state)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_manual(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_manual(False)
