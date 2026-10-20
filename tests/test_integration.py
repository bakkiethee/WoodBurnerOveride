"""Run the integration inside a real Home Assistant core, with faked devices."""

import time
from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant.core import HomeAssistant, ServiceCall  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.wood_stove_mode.const import DOMAIN  # noqa: E402

STOVE = ["sensor.stove_1", "sensor.stove_2"]
EXCH = ["sensor.exch_1", "sensor.exch_2"]
WATER = "sensor.system_water"
SAT = "climate.sat"
NEST = "climate.nest"
LIVING = "climate.living"
BEDROOM = "climate.bedroom"

ROOMS = [
    {
        "name": "Living",
        "climate": LIVING,
        "opening_entity": "number.living_opening",
        "inhibit_entity": "input_boolean.living_inhibit",
        "dump": True,
    },
    {
        "name": "Bedroom",
        "climate": BEDROOM,
        "opening_entity": "number.bedroom_opening",
        "inhibit_entity": "input_boolean.bedroom_inhibit",
        "dump": False,
    },
]


@pytest.fixture(autouse=True)
def _enable(enable_custom_integrations):
    yield


def _vt_state(hass, entity_id, inhibited, mode="heat", target=20.0):
    hass.states.async_set(
        entity_id,
        "off" if inhibited else mode,
        {
            "temperature": target,
            "preset_mode": "none",
            "specific_states": {"inhibition": {"inhibited": inhibited}},
        },
    )


def _set_sensors(hass, stove=20.0, exch=20.0, water=40.0):
    for entity in STOVE:
        hass.states.async_set(entity, str(stove))
    for entity in EXCH:
        hass.states.async_set(entity, str(exch))
    hass.states.async_set(WATER, str(water))


class Calls:
    """Records service calls and lets the fake VT react to the inhibition helpers."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.log: list[tuple[str, str, dict]] = []
        for domain, service in (
            ("climate", "turn_off"),
            ("climate", "set_hvac_mode"),
            ("climate", "set_temperature"),
            ("climate", "set_preset_mode"),
            ("number", "set_value"),
            ("notify", "test"),
            ("persistent_notification", "create"),
        ):
            hass.services.async_register(domain, service, self._record(domain, service))
        for service in ("turn_on", "turn_off"):
            hass.services.async_register("homeassistant", service, self._inhibit(service))

    def _record(self, domain, service):
        async def handler(call: ServiceCall) -> None:
            self.log.append((domain, service, dict(call.data)))

        return handler

    def _inhibit(self, service):
        async def handler(call: ServiceCall) -> None:
            self.log.append(("homeassistant", service, dict(call.data)))
            entity = call.data["entity_id"]
            climate = {"input_boolean.living_inhibit": LIVING, "input_boolean.bedroom_inhibit": BEDROOM}[entity]
            target = self.hass.states.get(climate).attributes["temperature"]
            _vt_state(self.hass, climate, inhibited=service == "turn_on", target=target)

        return handler

    def of(self, domain, service):
        return [d for dom, svc, d in self.log if (dom, svc) == (domain, service)]

    def names(self):
        return [f"{dom}.{svc}" for dom, svc, _ in self.log]


async def _setup(hass: HomeAssistant):
    _set_sensors(hass)
    hass.states.async_set(SAT, "heat")
    hass.states.async_set(NEST, "heat", {"temperature": 21.0})
    _vt_state(hass, LIVING, False)
    _vt_state(hass, BEDROOM, False, target=17.0)
    calls = Calls(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "stove_sensors": STOVE,
            "exchanger_sensors": EXCH,
            "water_sensor": WATER,
            "sat_entity": SAT,
            "nest_entity": NEST,
            "notify_service": "notify.test",
            "rooms": ROOMS,
        },
        options={"release_timeout": 5},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry, hass.data[DOMAIN][entry.entry_id], calls


async def test_boiler_mode_by_default(hass: HomeAssistant):
    entry, controller, calls = await _setup(hass)
    assert controller.engine.state.mode == "boiler"
    state = hass.states.get("sensor.wood_stove_mode_status")
    assert state.state == "boiler"
    assert not calls.of("climate", "turn_off")


async def test_stove_heat_starts_wood_mode_in_the_right_order(hass: HomeAssistant):
    entry, controller, calls = await _setup(hass)
    calls.log.clear()
    _set_sensors(hass, stove=62.0, exch=50.0)
    await controller._tick(None)
    await hass.async_block_till_done()

    names = calls.names()
    assert controller.engine.state.mode == "wood"
    # snapshot is internal; rooms are inhibited before SAT goes off, before openings.
    assert names.index("homeassistant.turn_on") < names.index("climate.turn_off")
    assert names.index("climate.turn_off") < names.index("number.set_value")
    assert {"entity_id": SAT} in calls.of("climate", "turn_off")
    assert any(d == {"entity_id": NEST, "temperature": 15.0} for d in calls.of("climate", "set_temperature"))
    writes = {d["entity_id"]: d["value"] for d in calls.of("number", "set_value")}
    assert writes == {"number.living_opening": 25, "number.bedroom_opening": 0}
    assert calls.of("notify", "test")  # wood mode started
    assert hass.states.get("switch.wood_stove_mode_wood_mode").state == "on"
    assert hass.states.get("sensor.wood_stove_mode_status").state == "wood"


async def test_emergency_opens_every_room(hass: HomeAssistant):
    entry, controller, calls = await _setup(hass)
    _set_sensors(hass, stove=62.0, exch=50.0)
    await controller._tick(None)
    calls.log.clear()
    _set_sensors(hass, stove=62.0, exch=86.0)
    await controller._tick(None)
    writes = {d["entity_id"]: d["value"] for d in calls.of("number", "set_value")}
    assert writes == {"number.living_opening": 100, "number.bedroom_opening": 100}
    assert hass.states.get("sensor.wood_stove_mode_status").state == "emergency"


async def test_leaving_wood_mode_restores_settings_and_sat(hass: HomeAssistant):
    entry, controller, calls = await _setup(hass)
    _set_sensors(hass, stove=62.0, exch=50.0)
    await controller._tick(None)
    hass.states.async_set(SAT, "off")
    hass.states.async_set(NEST, "heat", {"temperature": 15.0})
    calls.log.clear()

    controller.engine.state.wood_since = time.time() - 4000
    _set_sensors(hass, stove=30.0, exch=40.0)
    await controller._tick(None)
    await hass.async_block_till_done()

    assert controller.engine.state.mode == "boiler"
    names = calls.names()
    assert names.index("homeassistant.turn_off") < names.index("climate.set_hvac_mode")
    restored = calls.of("climate", "set_temperature")
    assert {"entity_id": BEDROOM, "temperature": 17.0} in restored
    assert {"entity_id": NEST, "temperature": 21.0} in restored
    last_mode = calls.of("climate", "set_hvac_mode")[-1]
    assert last_mode == {"entity_id": SAT, "hvac_mode": "heat"}
    assert hass.states.get("switch.wood_stove_mode_wood_mode").state == "off"


async def test_manual_switch_starts_wood_mode(hass: HomeAssistant):
    entry, controller, calls = await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.wood_stove_mode_wood_mode"}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.engine.state.mode == "wood"


async def test_unload_in_wood_mode_opens_all_valves(hass: HomeAssistant):
    entry, controller, calls = await _setup(hass)
    _set_sensors(hass, stove=62.0, exch=50.0)
    await controller._tick(None)
    calls.log.clear()
    assert await hass.config_entries.async_unload(entry.entry_id)
    writes = {d["entity_id"]: d["value"] for d in calls.of("number", "set_value")}
    assert writes == {"number.living_opening": 100, "number.bedroom_opening": 100}


async def test_config_flow_creates_an_entry(hass: HomeAssistant):
    with patch(
        "custom_components.wood_stove_mode.async_setup_entry", return_value=True
    ):
        await _run_flow(hass)


async def _run_flow(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "stove_sensors": STOVE,
            "exchanger_sensors": EXCH,
            "water_sensor": WATER,
            "sat_entity": SAT,
        },
    )
    assert result["step_id"] == "room"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Living",
            "climate": LIVING,
            "opening_entity": "number.living_opening",
            "inhibit_entity": "input_boolean.living_inhibit",
            "dump": True,
            "add_another": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["rooms"][0]["climate"] == LIVING

