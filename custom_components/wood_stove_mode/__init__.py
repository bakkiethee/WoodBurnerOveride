"""Wood Stove Mode: pause SAT and dump stove heat through the TRVs."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant

from .const import DOMAIN
from .controller import WoodController

PLATFORMS = ["switch", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    controller = WoodController(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_update))

    def _start(_event=None) -> None:
        # Starting can wait for rooms to be inhibited, so it must not block the setup.
        entry.async_create_background_task(
            hass, controller.async_start(), "wood_stove_mode_start"
        )

    # Wait until Home Assistant has started so the sensors have their states.
    if hass.state is CoreState.running:
        _start()
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start)
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    controller: WoodController = hass.data[DOMAIN][entry.entry_id]
    await controller.async_stop()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded


async def _reload_on_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
