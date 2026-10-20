"""Decision engine for Wood Stove Mode.

This module has no Home Assistant imports. The controller feeds it sensor readings and
executes the ordered actions it returns, so every rule of the design can be tested
with plain Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .pid import Pid
from .readings import GroupResult, Reading, evaluate_group

BOILER = "boiler"
WOOD = "wood"


# ---------------------------------------------------------------- configuration


@dataclass
class EngineConfig:
    all_rooms: tuple[str, ...] = ()
    dump_rooms: tuple[str, ...] = ()
    stove_start_temp: float = 60.0
    exit_temp: float = 45.0
    min_wood_time: float = 30 * 60
    reentry_block: float = 10 * 60
    band_low: float = 60.0
    band_high: float = 70.0
    band_aim: float = 65.0
    water_target: float = 55.0
    update_interval: float = 120.0
    start_opening: float = 25.0
    emergency_temp: float = 85.0
    emergency_margin: float = 5.0  # the emergency ends below emergency_temp - margin
    nest_setpoint: float = 15.0
    sensor_diff_limit: float = 5.0
    sensor_diff_duration: float = 10 * 60
    stale_after: float = 5 * 60
    guard_interval: float = 30.0
    notify_interval: float = 10 * 60
    kp: float = 4.0
    ki: float = 0.01
    kd: float = 0.0

    @property
    def emergency_clear(self) -> float:
        return self.emergency_temp - self.emergency_margin


# ---------------------------------------------------------------------- inputs


@dataclass
class Inputs:
    now: float
    stove: list[Reading]
    exchanger: list[Reading]
    water: list[Reading]
    manual_on: bool = False
    sat_on: bool | None = None  # None when SAT state is unknown
    nest_setpoint: float | None = None


# --------------------------------------------------------------------- actions


@dataclass(frozen=True)
class Action:
    """Base class of everything the controller has to execute, in order."""


@dataclass(frozen=True)
class SaveSnapshot(Action):
    """Remember mode, target and preset of every room, the Nest and SAT."""


@dataclass(frozen=True)
class RestoreSnapshot(Action):
    """Restore the saved room and Nest settings, if a snapshot exists."""


@dataclass(frozen=True)
class InhibitRooms(Action):
    rooms: tuple[str, ...]
    on: bool


@dataclass(frozen=True)
class WaitInhibition(Action):
    """Wait until the rooms report the expected inhibition state (retry once)."""

    rooms: tuple[str, ...]
    inhibited: bool


@dataclass(frozen=True)
class SetSat(Action):
    on: bool


@dataclass(frozen=True)
class SetNest(Action):
    setpoint: float


@dataclass(frozen=True)
class WriteOpenings(Action):
    openings: tuple[tuple[str, int], ...]  # (room, percent)


@dataclass(frozen=True)
class SetManualSwitch(Action):
    on: bool


@dataclass(frozen=True)
class Notify(Action):
    key: str  # wood_start, wood_end, emergency, nest_reset, sat_guard, fault, info
    message: str


# ----------------------------------------------------------------------- state


@dataclass
class EngineState:
    mode: str = BOILER
    wood_since: float | None = None
    last_exit: float | None = None
    emergency: bool = False
    last_opening: float = 0.0
    last_update: float | None = None
    last_write_all: float | None = None
    prev_manual: bool = False
    pid_source: str | None = None
    diff_since: dict[str, float | None] = field(
        default_factory=lambda: {"stove": None, "exchanger": None}
    )
    faults: list[str] = field(default_factory=list)
    last_notify: dict[str, float] = field(default_factory=dict)
    last_guard: dict[str, float] = field(default_factory=dict)
    exchanger_failsafe: bool = False

    def export(self) -> dict:
        return {
            "mode": self.mode,
            "wood_since": self.wood_since,
            "last_exit": self.last_exit,
            "emergency": self.emergency,
            "last_opening": self.last_opening,
            "last_update": self.last_update,
            "prev_manual": self.prev_manual,
            "pid_source": self.pid_source,
            "diff_since": dict(self.diff_since),
            "faults": list(self.faults),
            "last_notify": dict(self.last_notify),
            "exchanger_failsafe": self.exchanger_failsafe,
        }

    @classmethod
    def restore(cls, data: dict | None) -> "EngineState":
        state = cls()
        if not data:
            return state
        state.mode = data.get("mode", BOILER)
        state.wood_since = data.get("wood_since")
        state.last_exit = data.get("last_exit")
        state.emergency = bool(data.get("emergency", False))
        state.last_opening = float(data.get("last_opening", 0.0))
        state.last_update = data.get("last_update")
        state.prev_manual = bool(data.get("prev_manual", False))
        state.pid_source = data.get("pid_source")
        state.diff_since = {"stove": None, "exchanger": None, **data.get("diff_since", {})}
        state.faults = list(data.get("faults", []))
        state.last_notify = dict(data.get("last_notify", {}))
        state.exchanger_failsafe = bool(data.get("exchanger_failsafe", False))
        return state


# ---------------------------------------------------------------------- engine


class WoodEngine:
    def __init__(self, config: EngineConfig, state: EngineState | None = None) -> None:
        self.config = config
        self.state = state or EngineState()
        self.pid = Pid(config.kp, config.ki, config.kd)

    # ------------------------------------------------------------- evaluation

    def _groups(self, inp: Inputs) -> tuple[GroupResult, GroupResult, GroupResult]:
        c = self.config
        return (
            evaluate_group(inp.stove, c.stale_after),
            evaluate_group(inp.exchanger, c.stale_after),
            evaluate_group(inp.water, c.stale_after),
        )

    def _exit_conditions_met(
        self, now: float, stove: GroupResult, exch: GroupResult
    ) -> bool:
        """Normal exit: min time passed, exchanger below exit temp, stove below start."""
        c, st = self.config, self.state
        if st.wood_since is not None and now - st.wood_since < c.min_wood_time:
            return False
        if exch.value is None or exch.value >= c.exit_temp:
            return False
        return stove.value is None or stove.value < c.stove_start_temp

    def _emergency_condition(
        self, mode: str, exch: GroupResult, water: GroupResult
    ) -> bool:
        c = self.config
        if exch.value is not None and exch.value >= c.emergency_temp:
            return True
        # The system water only counts in wood mode: in boiler mode a normal flow
        # temperature must not open every valve.
        return (
            mode == WOOD and water.value is not None and water.value >= c.emergency_temp
        )

    def _emergency_cleared(self, exch: GroupResult, water: GroupResult) -> bool:
        c = self.config
        if exch.value is None or exch.value >= c.emergency_clear:
            return False
        return water.value is None or water.value < c.emergency_clear

    # --------------------------------------------------------------- notifying

    def _notify_limited(
        self, now: float, key: str, message: str, out: list[Action]
    ) -> None:
        last = self.state.last_notify.get(key)
        if last is None or now - last >= self.config.notify_interval:
            self.state.last_notify[key] = now
            out.append(Notify(key, message))

    def _sensor_faults(
        self,
        now: float,
        stove: GroupResult,
        exch: GroupResult,
        water: GroupResult,
        out: list[Action],
    ) -> None:
        """Notify once when a sensor fault appears, and again when the set changes."""
        c, st = self.config, self.state
        faults: list[str] = []
        for name, group in (("stove", stove), ("exchanger", exch)):
            if group.all_failed:
                faults.append(f"{name}:all")
            else:
                for index, bad in enumerate(group.failed):
                    if bad:
                        faults.append(f"{name}:{index + 1}")
            # A large difference that lasts is a fault, but the highest reading stays in use.
            if group.difference is not None and group.difference > c.sensor_diff_limit:
                since = st.diff_since.get(name)
                if since is None:
                    st.diff_since[name] = now
                elif now - since >= c.sensor_diff_duration:
                    faults.append(f"{name}:diff")
            else:
                st.diff_since[name] = None
        if water.all_failed:
            faults.append("water:all")
        new = [f for f in faults if f not in st.faults]
        if new:
            out.append(Notify("fault", "Wood stove sensor fault: " + ", ".join(new)))
        st.faults = faults

    # ------------------------------------------------------------ opening plan

    def _all_open(self, now: float) -> WriteOpenings:
        self.state.last_write_all = now
        return WriteOpenings(tuple((room, 100) for room in self.config.all_rooms))

    def _plan(self, dump_percent: int) -> WriteOpenings:
        c = self.config
        dump = set(c.dump_rooms)
        return WriteOpenings(
            tuple(
                (room, dump_percent if room in dump else 0) for room in c.all_rooms
            )
        )

    def _loop_update(
        self,
        now: float,
        exch: GroupResult,
        water: GroupResult,
    ) -> WriteOpenings:
        """One PID step: exchanger band first, system water inside the band."""
        c, st = self.config, self.state
        assert exch.value is not None
        in_band = c.band_low <= exch.value <= c.band_high
        if in_band and water.value is not None:
            source, error = "water", water.value - c.water_target
        else:
            source, error = "exchanger", exch.value - c.band_aim
        if source != st.pid_source:
            # Switching targets must not make the valves jump.
            self.pid.preset(st.last_opening, error)
            st.pid_source = source
        opening = int(round(self.pid.update(error, now)))
        opening = max(0, min(100, opening))
        st.last_opening = float(opening)
        st.last_update = now
        return self._plan(opening)

    # ------------------------------------------------------------ transitions

    def _enter_wood(
        self, now: float, emergency: bool, reason: str, out: list[Action]
    ) -> None:
        c, st = self.config, self.state
        rooms = tuple(c.all_rooms)
        out.extend(
            [
                SaveSnapshot(),
                InhibitRooms(rooms, True),
                WaitInhibition(rooms, True),
                SetSat(False),
                SetNest(c.nest_setpoint),
            ]
        )
        st.mode = WOOD
        st.wood_since = now
        st.prev_manual = True
        st.pid_source = None
        out.append(SetManualSwitch(True))
        if emergency:
            st.emergency = True
            st.last_opening = 100.0
            out.append(self._all_open(now))
            out.append(Notify("emergency", f"Emergency overheat: all valves opened ({reason})"))
        else:
            st.emergency = False
            st.last_opening = c.start_opening
            out.append(self._plan(int(round(c.start_opening))))
        self.pid.preset(st.last_opening)
        st.last_update = now
        out.append(Notify("wood_start", f"Wood stove mode started ({reason})"))

    def _exit_wood(self, now: float, reason: str, out: list[Action]) -> None:
        c, st = self.config, self.state
        rooms = tuple(c.all_rooms)
        # Release the rooms first, then restore their settings, then hand back to SAT,
        # so SAT's cascade cannot overwrite what was restored.
        out.extend(
            [
                InhibitRooms(rooms, False),
                WaitInhibition(rooms, False),
                RestoreSnapshot(),
                SetSat(True),
                SetManualSwitch(False),
                Notify("wood_end", f"Wood stove mode ended ({reason})"),
            ]
        )
        st.mode = BOILER
        st.wood_since = None
        st.last_exit = now
        st.emergency = False
        st.exchanger_failsafe = False
        st.prev_manual = False
        st.pid_source = None

    # -------------------------------------------------------------------- step

    def step(self, inp: Inputs) -> list[Action]:
        """Evaluate one tick and return the ordered actions to execute."""
        c, st = self.config, self.state
        now = inp.now
        out: list[Action] = []
        stove, exch, water = self._groups(inp)
        self._sensor_faults(now, stove, exch, water, out)

        manual_on_edge = inp.manual_on and not st.prev_manual
        manual_off_edge = (not inp.manual_on) and st.prev_manual
        emergency_now = self._emergency_condition(st.mode, exch, water)

        if st.mode == BOILER:
            st.prev_manual = inp.manual_on
            if emergency_now:
                self._enter_wood(now, True, "temperature above the emergency limit", out)
            elif manual_on_edge:
                self._enter_wood(now, False, "manual switch", out)
            elif st.last_exit is None or now - st.last_exit >= c.reentry_block:
                stove_hot = stove.value is not None and stove.value >= c.stove_start_temp
                fallback = (
                    stove.all_failed
                    and exch.value is not None
                    and exch.value >= c.stove_start_temp
                )
                if stove_hot:
                    self._enter_wood(now, False, "stove sensor", out)
                elif fallback:
                    self._enter_wood(now, False, "exchanger sensor, stove sensors failed", out)
            return out

        # ---------------------------------------------------------- wood mode
        force_update = False

        if emergency_now and not st.emergency:
            st.emergency = True
            st.last_opening = 100.0
            out.append(self._all_open(now))
            out.append(Notify("emergency", "Emergency overheat: all valves opened"))
        elif st.emergency:
            if self._emergency_cleared(exch, water):
                st.emergency = False
                self.pid.preset(100.0)
                st.pid_source = None
                force_update = True
                out.append(Notify("info", "Emergency ended, normal valve control resumed"))
            elif st.last_write_all is None or now - st.last_write_all >= c.update_interval:
                out.append(self._all_open(now))

        if not st.emergency and exch.all_failed:
            # Without the exchanger reading nothing can be regulated: fully open.
            if not st.exchanger_failsafe:
                st.exchanger_failsafe = True
                st.last_opening = 100.0
                out.append(self._all_open(now))
                out.append(
                    Notify("fault", "Both heat exchanger sensors failed: all valves opened")
                )
            elif st.last_write_all is None or now - st.last_write_all >= c.update_interval:
                out.append(self._all_open(now))
        elif st.exchanger_failsafe and not exch.all_failed:
            st.exchanger_failsafe = False
            self.pid.preset(100.0)
            st.pid_source = None
            force_update = True

        # ------------------------------------------------------------- exit
        if not st.emergency:
            if manual_off_edge:
                if stove.value is not None and stove.value < c.stove_start_temp:
                    st.prev_manual = False
                    self._exit_wood(now, "manual switch", out)
                    return out
                out.append(
                    Notify(
                        "info",
                        "Manual off ignored: the stove sensor is still at or above "
                        f"{c.stove_start_temp:g} °C",
                    )
                )
                out.append(SetManualSwitch(True))
                st.prev_manual = True
            elif self._exit_conditions_met(now, stove, exch):
                self._exit_wood(now, "heat exchanger cooled down", out)
                return out

        # ----------------------------------------------------------- guards
        reapply = False
        if inp.nest_setpoint is not None and abs(inp.nest_setpoint - c.nest_setpoint) > 0.01:
            if self._guard_due("nest", now):
                out.append(SetNest(c.nest_setpoint))
                self._notify_limited(
                    now, "nest_reset", "Nest setpoint was changed during wood mode and reset", out
                )
        if inp.sat_on:
            if self._guard_due("sat", now):
                out.append(SetSat(False))
                reapply = True
                self._notify_limited(
                    now, "sat_guard", "SAT was turned on during wood mode and turned off again", out
                )

        # -------------------------------------------------------- valve loop
        if st.emergency or st.exchanger_failsafe:
            return out
        if reapply:
            out.append(self._plan(int(round(st.last_opening))))
        due = st.last_update is None or now - st.last_update >= c.update_interval
        if (due or force_update) and exch.value is not None:
            out.append(self._loop_update(now, exch, water))
        return out

    def _guard_due(self, name: str, now: float) -> bool:
        last = self.state.last_guard.get(name)
        if last is None or now - last >= self.config.guard_interval:
            self.state.last_guard[name] = now
            return True
        return False

    # ---------------------------------------------------- startup and shutdown

    def startup(self, inp: Inputs) -> list[Action]:
        """Pick a mode after a Home Assistant restart or an integration reload."""
        c, st = self.config, self.state
        now = inp.now
        stove, exch, water = self._groups(inp)
        out: list[Action] = []
        rooms = tuple(c.all_rooms)
        st.prev_manual = inp.manual_on

        if st.mode == WOOD:
            if not st.emergency and self._exit_conditions_met(now, stove, exch):
                self._exit_wood(now, "restart, exit conditions met", out)
                return out
            # Stay in wood mode: inhibition may have been lost, so set it again.
            out.extend(
                [
                    InhibitRooms(rooms, True),
                    WaitInhibition(rooms, True),
                    SetSat(False),
                    SetNest(c.nest_setpoint),
                    SetManualSwitch(True),
                ]
            )
            st.prev_manual = True
            self.pid.preset(st.last_opening)
            st.pid_source = None
            st.last_update = None  # a valve step is due on the next tick
            if st.emergency or self._emergency_condition(WOOD, exch, water):
                st.emergency = True
                out.append(self._all_open(now))
            elif exch.all_failed:
                st.exchanger_failsafe = True
                out.append(self._all_open(now))
            return out

        if stove.value is not None and stove.value >= c.stove_start_temp:
            self._enter_wood(now, False, "stove sensor at startup", out)
            return out
        if self._emergency_condition(BOILER, exch, water):
            self._enter_wood(now, True, "temperature above the emergency limit", out)
            return out
        out.extend(
            [InhibitRooms(rooms, False), WaitInhibition(rooms, False), RestoreSnapshot()]
        )
        return out

    def shutdown(self, now: float) -> list[Action]:
        """Leave the valves fully open if the integration unloads in wood mode."""
        if self.state.mode != WOOD:
            return []
        return [
            self._all_open(now),
            Notify("fault", "Wood stove integration unloaded in wood mode: all valves opened"),
        ]
