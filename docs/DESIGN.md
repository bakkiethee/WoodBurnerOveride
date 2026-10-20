# Wood Stove Mode: design

This is the approved design the integration is built from.

## Problem

The house has a boiler and a wood stove. SAT controls the heat through the OpenTherm
Gateway (OTGW) to the living room and several rooms with TRVs. On boiler alone this
works. When the stove burns, it also heats the boiler water, and SAT keeps regulating
as if only the boiler were heating, so the system can overheat. SAT cannot be used
then, and the excess heat has to be dumped into chosen rooms.

## Inputs

| Input | Purpose |
| --- | --- |
| Wood stove temperature sensors (two, redundant) | Starts wood mode at 60 °C |
| Heat exchanger temperature sensors (two, redundant, boiler room) | Priority control value (60 to 70 °C), exit signal below 45 °C |
| Boiler system water temperature (from the OTGW) | Secondary control value (55 °C) while the exchanger is inside its band |
| Manual wood-mode switch | Forces wood mode, in addition to the automatic rules |

The highest of the two readings at a location is used. If one sensor fails, the other
is used and a notification is sent. A difference of more than 5 °C for 10 minutes is a
fault: notify and keep using the highest reading.

## Modes

Boiler mode (SAT in control) and wood mode (SAT paused).

* **Boiler to wood:** stove temperature reaches 60 °C, or the manual switch is turned
  on. An exchanger reading of 85 °C or more also enters wood mode (emergency).
* **Wood to boiler:** heat exchanger below 45 °C **and** stove sensor below 60 °C,
  after at least 30 minutes in wood mode. Wood mode cannot start again within 10
  minutes of ending (the manual switch and the emergency are exempt).

## Entering wood mode (order matters)

1. Save the settings of every room (mode, target, preset), the thermostat and SAT.
2. Inhibit every TRV room (vtherm_inhibition) and wait until each reports inhibited.
3. Turn SAT off (its climate entity). SAT has no pause setting.
4. Set the thermostat that talks to the OTGW to 15 °C.
5. Write the valve openings directly: dump rooms 25 %, every other room 0 %.

Versatile Thermostat's sleep mode is not used: it is blocked on inhibited rooms.
Openings are written only while rooms are inhibited, because VT writes its own
opening when inhibition ends.

## Leaving wood mode (order matters)

1. Release the inhibition of every room and wait until each is back on heat.
2. Restore the saved room settings and the thermostat.
3. Turn SAT back on.

## Control loop

* **Priority:** heat exchanger between 60 and 70 °C, aim 65 °C. Below the band the
  valves close down, above it they open further.
* **Secondary:** system water at 55 °C, used only while the exchanger is inside the
  band.
* One shared opening for the dump rooms from a PID controller with fixed, tunable
  gains. The integral term stops growing while the output is at its limits and during
  the 2 minute hold, and the loop continues from the last opening when the target
  changes, so the valves never jump.
* At most one valve change every 2 minutes. The emergency step is exempt.

## Fail-safes

* **Emergency:** at 85 °C on the heat exchanger (any mode) or the system water (wood
  mode only), 100 % is written to every TRV, not only the dump rooms. It ends when both
  temperatures are below 80 °C; the PID then restarts from 100 %. SAT's maximum boiler
  setpoint must stay below 85 °C (it is kept at 60 °C or lower), so a normal boiler
  flow never triggers it. No safety action depends on a notification being delivered.
* **Sensor failure:** a sensor has failed if it is unavailable, has not updated for 5
  minutes, or reads outside 0 to 110 °C. Both stove sensors failed: the exchanger
  reaching 60 °C is the entry signal. Both exchanger sensors failed in wood mode: write
  100 % to every TRV and notify. System water failed: drop the 55 °C target and keep
  the exchanger loop.
* **Restart:** mode, saved settings and timers are stored. After a restart the
  integration stays in wood mode if the stored mode was wood and the exit conditions
  are not met yet; it re-inhibits every room and resumes the loop.
* **Unload:** in wood mode the integration first writes 100 % to every TRV, so valves
  are never left frozen at a partial opening.
* **SAT guard:** if SAT is turned on during wood mode, it is turned off again within a
  minute and the openings are re-applied.
* **Thermostat guard:** if the thermostat setpoint is changed during wood mode, it is
  reset to 15 °C within a minute.
* **Manual switch:** on forces wood mode. Off ends wood mode only if the stove sensor
  is below 60 °C; otherwise it is ignored and a notification is sent.
* **Notifications:** guard actions send at most one notification per 10 minutes.
* **Circulation:** the boiler pump runs continuously (set in the boiler's own menu).

## Configuration

Everything is configurable: sensors, SAT and thermostat entities, rooms (and which
ones dump heat), start and exit temperatures, the minimum time in wood mode, the band
and its aim, the water target, the 2 minute limit, the start opening (25 %), the
emergency temperature (85 %), PID gains, sensor limits, the release timeout,
notification toggles and the notify service.
