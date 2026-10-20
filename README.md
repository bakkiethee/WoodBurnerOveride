# Wood Stove Mode

A Home Assistant custom integration for a house with a boiler and a wood stove that
both heat the same water circuit. When the stove is the main heat source, the
integration pauses [SAT](https://github.com/Alexwijn/SAT), puts the stove heat into
chosen rooms through their TRVs, and protects the system from overheating.

> Status: first build, version 0.1.0. The decision logic is covered by unit tests, and
> the Home Assistant side is tested in Home Assistant's test environment with simulated
> devices. It has not run on a real system yet, so test it on one room first.

## What it does

* **Starts wood mode** when the wood stove temperature reaches 60 °C (configurable),
  or when you turn the manual switch on.
* **Pauses SAT** by turning its climate entity off, and sets the thermostat that talks
  to the OpenTherm Gateway to 15 °C so a high request cannot start the boiler.
* **Takes over the TRVs.** Every TRV room is inhibited with the
  `vtherm_inhibition` plugin (installed through HACS) for Versatile Thermostat (10.6.1 or
  newer), and the integration writes the valve openings itself. The dump rooms start
  at 25 % and are adjusted by a PID controller; all other rooms are held closed.
* **Regulates two temperatures**: the heat exchanger stays between 60 and 70 °C (this
  has priority), and while it is inside that band the boiler system water is held at
  55 °C. Valves change at most once every 2 minutes.
* **Emergency step**: at 85 °C on the heat exchanger (or the system water in wood
  mode) every TRV is opened to 100 % at once, whatever the 2 minute limit.
* **Ends wood mode** when the heat exchanger is below 45 °C and the stove sensor is
  below 60 °C, after at least 30 minutes. Rooms are released, their settings and the
  thermostat are restored, and SAT is turned back on.

The full rules, including all fail-safes (sensor failures, restarts, guards against
someone turning SAT on or changing the thermostat), are in [docs/DESIGN.md](docs/DESIGN.md).

## Requirements

* Home Assistant 2026.2 or newer (developed and tested against 2026.2)
* [SAT](https://github.com/Alexwijn/SAT) climate entity
* [Versatile Thermostat](https://github.com/jmcollin78/versatile_thermostat) 10.6.1 or
  newer, one thermostat per TRV room, with a valve opening entity per room
* The `vtherm_inhibition` plugin 0.2.1, with plugin delays set to about 5 seconds and
  its unavailable grace period set to 60 seconds
* Two temperature sensors at the wood stove, two at the heat exchanger, and the boiler
  system water temperature from the OTGW. Sensors must report at least every 5
  minutes, or they count as failed.
* In the boiler's own menu, the pump set to run continuously, so water keeps moving
  through the radiators while SAT is off
* SAT's maximum setpoint kept at 60 °C or lower, so normal boiler operation never
  reaches the emergency temperature

## Installation

1. Add this repository to HACS as a custom repository (type: Integration), or copy
   `custom_components/wood_stove_mode` into your Home Assistant `custom_components`
   folder.
2. Restart Home Assistant.
3. For each TRV room, create an `input_boolean` helper and add a `vtherm_inhibition`
   entry for that room's thermostat that watches the helper.
4. Add the integration under Settings, Devices & services, and pick the sensors, the
   SAT entity, the thermostat, and each room (thermostat, valve opening entity,
   inhibition helper, and whether it dumps heat).

All thresholds, PID gains and notification options are under the integration's
Configure button.

## Entities

* `switch.wood_stove_mode_wood_mode`: forces wood mode on. Turning it off ends wood
  mode only if the stove sensor is below 60 °C. It also shows on while wood mode runs.
* `sensor.wood_stove_mode_status`: `boiler`, `wood`, `emergency` or `failsafe`, with the
  temperatures, the valve opening, the control source and sensor faults as attributes.
* `sensor.wood_stove_mode_valve_opening`: the shared valve opening in wood mode.

## Development

The decision logic (`engine.py`, `pid.py`, `readings.py`) does not import Home
Assistant and is tested with plain pytest:

```
pip install pytest
python -m pytest
```

The integration tests (`tests/test_integration.py`) run inside a Home Assistant test
environment and are skipped when Home Assistant is not installed:

```
pip install -r requirements_test.txt
python -m pytest
```

## Safety

This integration controls heating. Test it on one room before using it for the whole
house, and keep working mechanical overheat protection on the stove and boiler. Nothing
here replaces that.
