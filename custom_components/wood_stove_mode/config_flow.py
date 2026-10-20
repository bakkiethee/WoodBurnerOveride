"""Config and options flow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BAND_AIM,
    CONF_BAND_HIGH,
    CONF_BAND_LOW,
    CONF_EMERGENCY_TEMP,
    CONF_EXCHANGER_SENSORS,
    CONF_EXIT_TEMP,
    CONF_MIN_WOOD_MINUTES,
    CONF_NEST_ENTITY,
    CONF_NEST_SETPOINT,
    CONF_NOTIFY_EMERGENCY,
    CONF_NOTIFY_MODE,
    CONF_NOTIFY_NEST,
    CONF_NOTIFY_SERVICE,
    CONF_PID_KD,
    CONF_PID_KI,
    CONF_PID_KP,
    CONF_REENTRY_MINUTES,
    CONF_RELEASE_TIMEOUT,
    CONF_ROOM_CLIMATE,
    CONF_ROOM_DUMP,
    CONF_ROOM_INHIBIT,
    CONF_ROOM_NAME,
    CONF_ROOM_OPENING,
    CONF_ROOMS,
    CONF_SAT_ENTITY,
    CONF_SENSOR_DIFF,
    CONF_STALE_MINUTES,
    CONF_START_OPENING,
    CONF_STOVE_SENSORS,
    CONF_STOVE_START_TEMP,
    CONF_UPDATE_SECONDS,
    CONF_WATER_SENSOR,
    CONF_WATER_TARGET,
    DEFAULTS,
    DOMAIN,
)

ADD_ANOTHER = "add_another"


def _entity(*domains: str, multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=list(domains), multiple=multiple)
    )


def _number(minimum: float, maximum: float, step: float, unit: str | None = None):
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _room_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ROOM_NAME): str,
            vol.Required(CONF_ROOM_CLIMATE): _entity("climate"),
            vol.Required(CONF_ROOM_OPENING): _entity("number", "input_number"),
            vol.Required(CONF_ROOM_INHIBIT): _entity("input_boolean", "switch"),
            vol.Required(CONF_ROOM_DUMP, default=False): bool,
        }
    )


def _settings_schema(current: dict[str, Any]) -> vol.Schema:
    def d(key: str) -> Any:
        return current.get(key, DEFAULTS.get(key))

    return vol.Schema(
        {
            vol.Required(CONF_STOVE_START_TEMP, default=d(CONF_STOVE_START_TEMP)): _number(30, 95, 1, "°C"),
            vol.Required(CONF_EXIT_TEMP, default=d(CONF_EXIT_TEMP)): _number(20, 80, 1, "°C"),
            vol.Required(CONF_MIN_WOOD_MINUTES, default=d(CONF_MIN_WOOD_MINUTES)): _number(0, 240, 1, "min"),
            vol.Required(CONF_REENTRY_MINUTES, default=d(CONF_REENTRY_MINUTES)): _number(0, 120, 1, "min"),
            vol.Required(CONF_BAND_LOW, default=d(CONF_BAND_LOW)): _number(30, 95, 1, "°C"),
            vol.Required(CONF_BAND_HIGH, default=d(CONF_BAND_HIGH)): _number(30, 95, 1, "°C"),
            vol.Required(CONF_BAND_AIM, default=d(CONF_BAND_AIM)): _number(30, 95, 1, "°C"),
            vol.Required(CONF_WATER_TARGET, default=d(CONF_WATER_TARGET)): _number(20, 90, 1, "°C"),
            vol.Required(CONF_UPDATE_SECONDS, default=d(CONF_UPDATE_SECONDS)): _number(30, 900, 1, "s"),
            vol.Required(CONF_START_OPENING, default=d(CONF_START_OPENING)): _number(0, 100, 1, "%"),
            vol.Required(CONF_EMERGENCY_TEMP, default=d(CONF_EMERGENCY_TEMP)): _number(60, 100, 1, "°C"),
            vol.Required(CONF_NEST_SETPOINT, default=d(CONF_NEST_SETPOINT)): _number(5, 25, 0.5, "°C"),
            vol.Required(CONF_SENSOR_DIFF, default=d(CONF_SENSOR_DIFF)): _number(1, 30, 0.5, "°C"),
            vol.Required(CONF_STALE_MINUTES, default=d(CONF_STALE_MINUTES)): _number(1, 60, 1, "min"),
            vol.Required(CONF_RELEASE_TIMEOUT, default=d(CONF_RELEASE_TIMEOUT)): _number(5, 300, 1, "s"),
            vol.Required(CONF_PID_KP, default=d(CONF_PID_KP)): _number(0, 100, 0.1),
            vol.Required(CONF_PID_KI, default=d(CONF_PID_KI)): _number(0, 10, 0.001),
            vol.Required(CONF_PID_KD, default=d(CONF_PID_KD)): _number(0, 1000, 0.1),
            vol.Required(CONF_NOTIFY_MODE, default=d(CONF_NOTIFY_MODE)): bool,
            vol.Required(CONF_NOTIFY_EMERGENCY, default=d(CONF_NOTIFY_EMERGENCY)): bool,
            vol.Required(CONF_NOTIFY_NEST, default=d(CONF_NOTIFY_NEST)): bool,
            vol.Optional(
                CONF_NOTIFY_SERVICE, description={"suggested_value": current.get(CONF_NOTIFY_SERVICE)}
            ): str,
        }
    )


def _check_settings(values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if values[CONF_BAND_LOW] >= values[CONF_BAND_HIGH]:
        errors["base"] = "band_order"
    elif not values[CONF_BAND_LOW] <= values[CONF_BAND_AIM] <= values[CONF_BAND_HIGH]:
        errors["base"] = "aim_outside_band"
    elif values[CONF_EMERGENCY_TEMP] <= values[CONF_BAND_HIGH]:
        errors["base"] = "emergency_too_low"
    return errors


class WoodStoveModeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._rooms: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_STOVE_SENSORS] or not user_input[CONF_EXCHANGER_SENSORS]:
                errors["base"] = "sensors_required"
            else:
                self._data = dict(user_input)
                return await self.async_step_room()
        schema = vol.Schema(
            {
                vol.Required(CONF_STOVE_SENSORS): _entity("sensor", multiple=True),
                vol.Required(CONF_EXCHANGER_SENSORS): _entity("sensor", multiple=True),
                vol.Required(CONF_WATER_SENSOR): _entity("sensor"),
                vol.Required(CONF_SAT_ENTITY): _entity("climate"),
                vol.Optional(CONF_NEST_ENTITY): _entity("climate"),
                vol.Optional(CONF_NOTIFY_SERVICE): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_room(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            add_more = user_input.pop(ADD_ANOTHER, False)
            self._rooms.append(user_input)
            if add_more:
                return await self.async_step_room()
            return self.async_create_entry(
                title="Wood Stove Mode",
                data={**self._data, CONF_ROOMS: self._rooms},
            )
        schema = _room_schema().extend({vol.Required(ADD_ANOTHER, default=False): bool})
        return self.async_show_form(step_id="room", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return WoodStoveModeOptionsFlow()


class WoodStoveModeOptionsFlow(OptionsFlow):
    """Edit thresholds and notifications, or add and remove rooms."""

    def _current_rooms(self) -> list[dict[str, Any]]:
        return list(
            self.config_entry.options.get(
                CONF_ROOMS, self.config_entry.data.get(CONF_ROOMS, [])
            )
        )

    def _save(self, **changes: Any):
        options = {**self.config_entry.options, **changes}
        return self.async_create_entry(data=options)

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "add_room", "remove_room"]
        )

    async def async_step_settings(self, user_input: dict[str, Any] | None = None):
        current = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _check_settings(user_input)
            if not errors:
                return self._save(**user_input)
            current = {**current, **user_input}
        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema(current), errors=errors
        )

    async def async_step_add_room(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self._save(**{CONF_ROOMS: [*self._current_rooms(), user_input]})
        return self.async_show_form(step_id="add_room", data_schema=_room_schema())

    async def async_step_remove_room(self, user_input: dict[str, Any] | None = None):
        rooms = self._current_rooms()
        names = {r[CONF_ROOM_CLIMATE]: r[CONF_ROOM_NAME] for r in rooms}
        if user_input is not None:
            keep = [r for r in rooms if r[CONF_ROOM_CLIMATE] not in user_input["remove"]]
            return self._save(**{CONF_ROOMS: keep})
        schema = vol.Schema(
            {
                vol.Required("remove", default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[{"value": k, "label": v} for k, v in names.items()],
                        multiple=True,
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove_room", data_schema=schema)
