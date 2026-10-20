"""Home Assistant side of Wood Stove Mode: reads entities, runs the engine, acts."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

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
    STORAGE_VERSION,
    TICK_SECONDS,
)
from .engine import (
    BOILER,
    EngineConfig,
    EngineState,
    InhibitRooms,
    Inputs,
    Notify,
    RestoreSnapshot,
    SaveSnapshot,
    SetManualSwitch,
    SetNest,
    SetSat,
    WaitInhibition,
    WoodEngine,
    WriteOpenings,
)
from .readings import Reading

_LOGGER = logging.getLogger(__name__)

NOTIFY_TOGGLES = {
    "wood_start": CONF_NOTIFY_MODE,
    "wood_end": CONF_NOTIFY_MODE,
    "emergency": CONF_NOTIFY_EMERGENCY,
    "nest_reset": CONF_NOTIFY_NEST,
}


def _opt(entry: ConfigEntry, key: str) -> Any:
    """Options win over the data from the first setup, then the defaults."""
    if key in entry.options:
        return entry.options[key]
    if key in entry.data:
        return entry.data[key]
    return DEFAULTS.get(key)


def _is_inhibited(state: State | None) -> bool | None:
    """Inhibition status of a Versatile Thermostat, None when it cannot be known.

    A thermostat without the inhibition attribute (VT older than 10.6.1) counts as
    not inhibited, so waiting for inhibition ends in a notification, not in silence.
    """
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    specific = state.attributes.get("specific_states") or {}
    inhibition = specific.get("inhibition")
    return bool(inhibition.get("inhibited")) if isinstance(inhibition, dict) else False


class WoodController:
    """Owns the engine, the storage and every call into Home Assistant."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._lock = asyncio.Lock()
        self._unsub: list[Callable[[], None]] = []
        self._listeners: list[Callable[[], None]] = []
        self._snapshot: dict[str, Any] | None = None
        self.manual_on = False
        self.last_inputs: Inputs | None = None
        # Rooms edited in the options replace the ones from the first setup.
        self.rooms: list[dict[str, Any]] = list(
            entry.options.get(CONF_ROOMS, entry.data.get(CONF_ROOMS, []))
        )
        self._pending_sat: str | None = None
        self.engine = WoodEngine(self._engine_config())

    # ----------------------------------------------------------------- setup

    def _engine_config(self) -> EngineConfig:
        e = self.entry
        all_rooms = tuple(r[CONF_ROOM_CLIMATE] for r in self.rooms)
        dump = tuple(r[CONF_ROOM_CLIMATE] for r in self.rooms if r.get(CONF_ROOM_DUMP))
        return EngineConfig(
            all_rooms=all_rooms,
            dump_rooms=dump,
            stove_start_temp=float(_opt(e, CONF_STOVE_START_TEMP)),
            exit_temp=float(_opt(e, CONF_EXIT_TEMP)),
            min_wood_time=float(_opt(e, CONF_MIN_WOOD_MINUTES)) * 60,
            reentry_block=float(_opt(e, CONF_REENTRY_MINUTES)) * 60,
            band_low=float(_opt(e, CONF_BAND_LOW)),
            band_high=float(_opt(e, CONF_BAND_HIGH)),
            band_aim=float(_opt(e, CONF_BAND_AIM)),
            water_target=float(_opt(e, CONF_WATER_TARGET)),
            update_interval=float(_opt(e, CONF_UPDATE_SECONDS)),
            start_opening=float(_opt(e, CONF_START_OPENING)),
            emergency_temp=float(_opt(e, CONF_EMERGENCY_TEMP)),
            nest_setpoint=float(_opt(e, CONF_NEST_SETPOINT)),
            sensor_diff_limit=float(_opt(e, CONF_SENSOR_DIFF)),
            stale_after=float(_opt(e, CONF_STALE_MINUTES)) * 60,
            kp=float(_opt(e, CONF_PID_KP)),
            ki=float(_opt(e, CONF_PID_KI)),
            kd=float(_opt(e, CONF_PID_KD)),
        )

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.engine = WoodEngine(
            self._engine_config(), EngineState.restore(stored.get("engine"))
        )
        if stored.get("pid"):
            self.engine.pid.restore(stored["pid"])
        self._snapshot = stored.get("snapshot")
        self.manual_on = self.engine.state.mode != BOILER

        inputs = self._gather(time.time())
        async with self._lock:
            await self._execute(self.engine.startup(inputs))
        await self._save()
        self._unsub.append(
            async_track_time_interval(
                self.hass, self._tick, timedelta(seconds=TICK_SECONDS)
            )
        )
        self._notify_listeners()

    async def async_stop(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        async with self._lock:
            await self._execute(self.engine.shutdown(time.time()))
        await self._save()

    # ------------------------------------------------------------- listeners

    def async_add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)

        def remove() -> None:
            self._listeners.remove(update)

        return remove

    def _notify_listeners(self) -> None:
        for update in list(self._listeners):
            update()

    # --------------------------------------------------------- manual switch

    async def async_set_manual(self, on: bool) -> None:
        self.manual_on = on
        self._notify_listeners()
        await self._tick(None)

    # ------------------------------------------------------------------ tick

    async def _tick(self, _now: Any) -> None:
        if self._lock.locked():
            return  # the previous tick is still working (for example waiting for VT)
        async with self._lock:
            inputs = self._gather(time.time())
            before = self.engine.state.mode
            actions = self.engine.step(inputs)
            if actions:
                await self._execute(actions)
            await self._save(immediate=self.engine.state.mode != before)
        self._notify_listeners()

    def _reading(self, entity_id: str, now: float) -> Reading:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return Reading(None)
        try:
            value = float(state.state)
        except ValueError:
            return Reading(None)
        reported = getattr(state, "last_reported", None) or state.last_updated
        return Reading(value, max(now - reported.timestamp(), 0.0))

    def _gather(self, now: float) -> Inputs:
        e = self.entry
        sat = self.hass.states.get(e.data[CONF_SAT_ENTITY])
        sat_on: bool | None = None
        if sat is not None and sat.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            sat_on = sat.state != STATE_OFF
        nest_setpoint: float | None = None
        nest_id = e.data.get(CONF_NEST_ENTITY)
        if nest_id:
            nest = self.hass.states.get(nest_id)
            if nest is not None:
                try:
                    nest_setpoint = float(nest.attributes.get("temperature"))
                except (TypeError, ValueError):
                    nest_setpoint = None
        self.last_inputs = Inputs(
            now=now,
            stove=[self._reading(s, now) for s in e.data[CONF_STOVE_SENSORS]],
            exchanger=[self._reading(s, now) for s in e.data[CONF_EXCHANGER_SENSORS]],
            water=[self._reading(e.data[CONF_WATER_SENSOR], now)],
            manual_on=self.manual_on,
            sat_on=sat_on,
            nest_setpoint=nest_setpoint,
        )
        return self.last_inputs

    # --------------------------------------------------------------- storage

    async def _save(self, immediate: bool = True) -> None:
        data = {
            "engine": self.engine.state.export(),
            "pid": self.engine.pid.export(),
            "snapshot": self._snapshot,
        }
        if immediate:
            await self._store.async_save(data)
        else:
            self._store.async_delay_save(lambda: data, 10)

    # --------------------------------------------------------------- actions

    async def _execute(self, actions: list) -> None:
        for action in actions:
            try:
                await self._run(action)
            except Exception:  # noqa: BLE001 - one failed call must not stop the rest
                _LOGGER.exception("Wood stove action failed: %s", action)

    async def _run(self, action: Any) -> None:
        if isinstance(action, SaveSnapshot):
            await self._save_snapshot()
        elif isinstance(action, RestoreSnapshot):
            await self._restore_snapshot()
        elif isinstance(action, InhibitRooms):
            await self._set_inhibition(action.rooms, action.on)
        elif isinstance(action, WaitInhibition):
            await self._wait_inhibition(action.rooms, action.inhibited)
        elif isinstance(action, SetSat):
            await self._set_sat(action.on)
        elif isinstance(action, SetNest):
            await self._set_nest(action.setpoint)
        elif isinstance(action, WriteOpenings):
            await self._write_openings(action.openings)
        elif isinstance(action, SetManualSwitch):
            self.manual_on = action.on
            self._notify_listeners()
        elif isinstance(action, Notify):
            await self._notify(action)

    def _room(self, climate_id: str) -> dict[str, Any]:
        return next(r for r in self.rooms if r[CONF_ROOM_CLIMATE] == climate_id)

    async def _call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        await self.hass.services.async_call(domain, service, data, blocking=True)

    async def _save_snapshot(self) -> None:
        rooms: dict[str, Any] = {}
        for room in self.rooms:
            state = self.hass.states.get(room[CONF_ROOM_CLIMATE])
            if state is None:
                continue
            rooms[room[CONF_ROOM_CLIMATE]] = {
                "hvac_mode": state.state,
                "temperature": state.attributes.get("temperature"),
                "preset_mode": state.attributes.get("preset_mode"),
            }
        nest = self.hass.states.get(self.entry.data.get(CONF_NEST_ENTITY, ""))
        sat = self.hass.states.get(self.entry.data[CONF_SAT_ENTITY])
        self._snapshot = {
            "rooms": rooms,
            "nest": nest.attributes.get("temperature") if nest else None,
            "sat": sat.state if sat else None,
        }
        await self._save()

    async def _restore_snapshot(self) -> None:
        snap = self._snapshot
        if not snap:
            return
        for climate_id, saved in snap.get("rooms", {}).items():
            mode = saved.get("hvac_mode")
            if mode and mode not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                await self._call(
                    "climate", "set_hvac_mode", {"entity_id": climate_id, "hvac_mode": mode}
                )
            if saved.get("temperature") is not None:
                await self._call(
                    "climate",
                    "set_temperature",
                    {"entity_id": climate_id, "temperature": saved["temperature"]},
                )
            preset = saved.get("preset_mode")
            if preset and preset != "none":
                await self._call(
                    "climate",
                    "set_preset_mode",
                    {"entity_id": climate_id, "preset_mode": preset},
                )
        nest_id = self.entry.data.get(CONF_NEST_ENTITY)
        if nest_id and snap.get("nest") is not None:
            await self._call(
                "climate", "set_temperature", {"entity_id": nest_id, "temperature": snap["nest"]}
            )
        # SetSat(True) comes next and needs the SAT mode from before wood mode.
        self._pending_sat = snap.get("sat")
        self._snapshot = None
        await self._save()

    async def _set_inhibition(self, rooms: tuple[str, ...], on: bool) -> None:
        for climate_id in rooms:
            entity = self._room(climate_id)[CONF_ROOM_INHIBIT]
            await self._call("homeassistant", "turn_on" if on else "turn_off", {"entity_id": entity})

    async def _wait_inhibition(self, rooms: tuple[str, ...], inhibited: bool) -> None:
        timeout = float(_opt(self.entry, CONF_RELEASE_TIMEOUT))
        for attempt in (1, 2):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._rooms_in_state(rooms, inhibited):
                    return
                await asyncio.sleep(1)
            if attempt == 1:
                await self._notify(
                    Notify(
                        "fault",
                        "Rooms did not reach the expected inhibition state in time, retrying",
                    )
                )
                await self._set_inhibition(rooms, inhibited)
        await self._notify(
            Notify("fault", "Rooms still not in the expected inhibition state, continuing")
        )

    def _rooms_in_state(self, rooms: tuple[str, ...], inhibited: bool) -> bool:
        for climate_id in rooms:
            state = self.hass.states.get(climate_id)
            status = _is_inhibited(state)
            if status is None or status != inhibited:
                return False
            if not inhibited and state is not None and state.state == STATE_OFF:
                return False  # released, but VT is not back on heat yet
        return True

    async def _set_sat(self, on: bool) -> None:
        sat_id = self.entry.data[CONF_SAT_ENTITY]
        if not on:
            await self._call("climate", "turn_off", {"entity_id": sat_id})
            return
        mode = self._pending_sat
        if mode in (None, STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN):
            mode = "heat"
        await self._call("climate", "set_hvac_mode", {"entity_id": sat_id, "hvac_mode": mode})
        self._pending_sat = None

    async def _set_nest(self, setpoint: float) -> None:
        nest_id = self.entry.data.get(CONF_NEST_ENTITY)
        if nest_id:
            await self._call(
                "climate", "set_temperature", {"entity_id": nest_id, "temperature": setpoint}
            )

    async def _write_openings(self, openings: tuple[tuple[str, int], ...]) -> None:
        for climate_id, percent in openings:
            room = self._room(climate_id)
            if _is_inhibited(self.hass.states.get(climate_id)) is False:
                _LOGGER.warning(
                    "Writing %s%% to %s while it is not inhibited: VT may overwrite it",
                    percent,
                    room[CONF_ROOM_NAME],
                )
            entity = room[CONF_ROOM_OPENING]
            domain = entity.split(".", 1)[0]
            await self._call(domain, "set_value", {"entity_id": entity, "value": percent})

    async def _notify(self, action: Notify) -> None:
        toggle = NOTIFY_TOGGLES.get(action.key)
        if toggle and not _opt(self.entry, toggle):
            return
        service = _opt(self.entry, CONF_NOTIFY_SERVICE)
        try:
            if service:
                domain, _, name = service.rpartition(".")
                await self._call(
                    domain or "notify", name, {"title": "Wood stove mode", "message": action.message}
                )
            else:
                await self._call(
                    "persistent_notification",
                    "create",
                    {"title": "Wood stove mode", "message": action.message},
                )
        except Exception:  # noqa: BLE001 - no safety action depends on a notification
            _LOGGER.exception("Sending the notification failed: %s", action.message)
