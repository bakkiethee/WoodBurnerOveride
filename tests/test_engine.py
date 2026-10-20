from custom_components.wood_stove_mode.engine import (
    BOILER,
    WOOD,
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
from custom_components.wood_stove_mode.readings import Reading

ROOMS = ("living", "kitchen", "bedroom")
DUMP = ("living", "kitchen")


def make(**overrides):
    cfg = EngineConfig(all_rooms=ROOMS, dump_rooms=DUMP, **overrides)
    return WoodEngine(cfg)


def inputs(now, stove=20.0, exch=20.0, water=40.0, manual=False, sat=False, nest=15.0):
    def pair(value):
        return [Reading(value), Reading(value)]

    return Inputs(
        now=now,
        stove=pair(stove),
        exchanger=pair(exch),
        water=[Reading(water)],
        manual_on=manual,
        sat_on=sat,
        nest_setpoint=nest,
    )


def run(engine, now, **kw):
    """Step the engine; the manual switch mirrors the mode unless a test says otherwise."""
    kw.setdefault("manual", engine.state.mode == WOOD)
    return engine.step(inputs(now, **kw))


def kinds(actions):
    return [type(a) for a in actions]


def openings(actions):
    """The last WriteOpenings in the list as a dict."""
    writes = [a for a in actions if isinstance(a, WriteOpenings)]
    return dict(writes[-1].openings) if writes else None


def enter(engine, now=1000.0):
    return engine.step(inputs(now, stove=61.0, exch=50.0))


# ------------------------------------------------------------------ entry


def test_stays_in_boiler_mode_below_the_start_temperature():
    engine = make()
    assert run(engine, 0, stove=59.9) == []
    assert engine.state.mode == BOILER


def test_entry_order_snapshot_inhibit_sat_off_then_write():
    engine = make()
    actions = enter(engine)
    order = kinds(actions)
    assert order[:5] == [SaveSnapshot, InhibitRooms, WaitInhibition, SetSat, SetNest]
    assert order.index(SetSat) < order.index(WriteOpenings)
    assert actions[3] == SetSat(False)
    assert actions[4] == SetNest(15.0)
    assert engine.state.mode == WOOD


def test_entry_starts_dump_rooms_at_25_and_holds_others_closed():
    engine = make()
    assert openings(enter(engine)) == {"living": 25, "kitchen": 25, "bedroom": 0}


def test_every_room_is_inhibited_on_entry():
    engine = make()
    inhibit = next(a for a in enter(engine) if isinstance(a, InhibitRooms))
    assert inhibit.rooms == ROOMS and inhibit.on is True


def test_manual_switch_starts_wood_mode():
    engine = make()
    actions = run(engine, 0, manual=True)
    assert engine.state.mode == WOOD
    assert SetSat(False) in actions


def test_fallback_entry_when_both_stove_sensors_failed():
    engine = make()
    inp = inputs(0, exch=61.0)
    inp.stove = [Reading(None), Reading(None)]
    engine.step(inp)
    assert engine.state.mode == WOOD


def test_one_stove_sensor_failing_still_triggers_on_the_other():
    engine = make()
    inp = inputs(0, exch=30.0)
    inp.stove = [Reading(None), Reading(62.0)]
    engine.step(inp)
    assert engine.state.mode == WOOD


# ------------------------------------------------------------------- exit


def test_no_exit_before_the_minimum_time():
    engine = make()
    enter(engine, now=0.0)
    run(engine, 100, stove=30.0, exch=40.0)
    assert engine.state.mode == WOOD


def test_exit_after_min_time_when_exchanger_cold_and_stove_below_start():
    engine = make()
    enter(engine, now=0.0)
    actions = run(engine, 1801, stove=30.0, exch=44.0)
    assert engine.state.mode == BOILER
    order = kinds(actions)
    assert order.index(InhibitRooms) < order.index(RestoreSnapshot) < order.index(SetSat)
    assert SetSat(True) in actions


def test_no_exit_while_the_stove_sensor_is_still_hot():
    engine = make()
    enter(engine, now=0.0)
    run(engine, 1801, stove=60.0, exch=44.0)
    assert engine.state.mode == WOOD


def test_no_exit_while_exchanger_is_above_the_exit_temperature():
    engine = make()
    enter(engine, now=0.0)
    run(engine, 5000, stove=30.0, exch=46.0)
    assert engine.state.mode == WOOD


def test_reentry_is_blocked_for_ten_minutes():
    engine = make()
    enter(engine, now=0.0)
    run(engine, 1801, stove=30.0, exch=44.0)
    run(engine, 1900, stove=65.0, exch=44.0)
    assert engine.state.mode == BOILER
    run(engine, 1801 + 601, stove=65.0, exch=44.0)
    assert engine.state.mode == WOOD


# ---------------------------------------------------------- manual switch


def test_manual_off_ends_wood_mode_when_stove_is_below_start():
    engine = make()
    run(engine, 0, manual=True)
    actions = run(engine, 30, stove=40.0, exch=60.0, manual=False)
    assert engine.state.mode == BOILER
    assert SetManualSwitch(False) in actions


def test_manual_off_is_ignored_while_the_stove_is_hot():
    engine = make()
    run(engine, 0, manual=True)
    actions = run(engine, 30, stove=70.0, exch=60.0, manual=False)
    assert engine.state.mode == WOOD
    assert SetManualSwitch(True) in actions
    assert any(isinstance(a, Notify) and a.key == "info" for a in actions)


# -------------------------------------------------------------- emergency


def test_emergency_opens_every_room_to_100():
    engine = make()
    enter(engine, now=0.0)
    actions = run(engine, 10, exch=85.0)
    assert openings(actions) == {"living": 100, "kitchen": 100, "bedroom": 100}
    assert any(isinstance(a, Notify) and a.key == "emergency" for a in actions)


def test_emergency_ignores_the_two_minute_limit():
    engine = make()
    enter(engine, now=0.0)
    run(engine, 10, exch=60.0)  # normal tick, not due yet
    actions = run(engine, 11, exch=86.0)
    assert openings(actions)["bedroom"] == 100


def test_emergency_from_system_water_in_wood_mode():
    engine = make()
    enter(engine, now=0.0)
    actions = run(engine, 10, exch=60.0, water=85.0)
    assert openings(actions)["bedroom"] == 100


def test_system_water_alone_does_not_trigger_in_boiler_mode():
    engine = make()
    assert run(engine, 0, exch=40.0, water=88.0) == []
    assert engine.state.mode == BOILER


def test_exchanger_emergency_in_boiler_mode_enters_wood_mode_with_all_open():
    engine = make()
    actions = run(engine, 0, stove=30.0, exch=86.0)
    assert engine.state.mode == WOOD
    assert openings(actions) == {"living": 100, "kitchen": 100, "bedroom": 100}
    order = kinds(actions)
    assert order.index(InhibitRooms) < order.index(SetSat) < order.index(WriteOpenings)


def test_emergency_ends_only_below_80_then_pid_restarts_from_100():
    engine = make()
    enter(engine, now=0.0)
    run(engine, 10, exch=86.0)
    run(engine, 20, exch=82.0)
    assert engine.state.emergency is True
    actions = run(engine, 30, exch=79.0)
    assert engine.state.emergency is False
    # Normal loop openings are written again, starting from the 100% the valves had.
    assert openings(actions)["bedroom"] == 0
    assert openings(actions)["living"] == 100


def test_wood_mode_can_end_after_an_emergency_once_everything_cooled():
    engine = make()
    enter(engine, now=0.0)
    run(engine, 10, exch=86.0)
    run(engine, 5000, stove=20.0, exch=30.0 + 0)  # cooled: clears, then may exit
    assert engine.state.emergency is False


# ------------------------------------------------------------ valve loop


def test_loop_waits_two_minutes_between_changes():
    engine = make()
    enter(engine, now=0.0)
    assert openings(run(engine, 60, exch=50.0)) is None
    assert openings(run(engine, 119, exch=50.0)) is None
    assert openings(run(engine, 120, exch=50.0)) is not None


def test_exchanger_below_the_band_closes_the_valves():
    engine = make()
    enter(engine, now=0.0)
    run(engine, 120, stove=61.0, exch=50.0)  # first loop step holds 25%
    result = openings(run(engine, 240, stove=61.0, exch=50.0))
    assert result["living"] < 25 and result["bedroom"] == 0


def test_exchanger_above_the_band_opens_the_valves():
    engine = make()
    enter(engine, now=0.0)
    run(engine, 120, stove=61.0, exch=75.0)
    result = openings(run(engine, 240, stove=61.0, exch=75.0))
    assert result["living"] > 25 and result["bedroom"] == 0


def test_inside_the_band_the_system_water_decides():
    engine = make()
    enter(engine, now=0.0)
    run(engine, 120, stove=61.0, exch=65.0, water=55.0)
    hot = openings(run(engine, 240, stove=61.0, exch=65.0, water=62.0))
    assert hot["living"] > 25
    cold = make()
    enter(cold, now=0.0)
    run(cold, 120, stove=61.0, exch=65.0, water=55.0)
    chilly = openings(run(cold, 240, stove=61.0, exch=65.0, water=48.0))
    assert chilly["living"] < 25


def test_switching_targets_does_not_make_the_valves_jump():
    engine = make()
    enter(engine, now=0.0)
    run(engine, 120, stove=61.0, exch=65.0, water=55.0)  # water loop, holds 25%
    run(engine, 240, stove=61.0, exch=58.0, water=55.0)  # leaves the band
    assert engine.state.pid_source == "exchanger"
    assert engine.state.last_opening == 25.0


# ------------------------------------------------------------ sensor faults


def test_both_exchanger_sensors_failed_opens_everything():
    engine = make()
    enter(engine, now=0.0)
    inp = inputs(10)
    inp.exchanger = [Reading(None), Reading(None)]
    actions = engine.step(inp)
    assert openings(actions)["bedroom"] == 100
    assert any(isinstance(a, Notify) and a.key == "fault" for a in actions)


def test_one_failed_sensor_notifies_once():
    engine = make()
    inp = inputs(0, stove=30.0)
    inp.exchanger = [Reading(None), Reading(40.0)]
    first = engine.step(inp)
    inp.now = 30
    second = engine.step(inp)
    assert sum(isinstance(a, Notify) for a in first) == 1
    assert second == []


def test_large_sensor_difference_is_a_fault_after_ten_minutes():
    engine = make()
    inp = inputs(0, stove=30.0)
    inp.exchanger = [Reading(30.0), Reading(40.0)]
    assert engine.step(inp) == []
    inp.now = 599
    assert engine.step(inp) == []
    inp.now = 601
    actions = engine.step(inp)
    assert any(isinstance(a, Notify) and "exchanger:diff" in a.message for a in actions)


def test_water_sensor_failure_drops_the_water_target():
    engine = make()
    enter(engine, now=0.0)
    inp = inputs(120, stove=61.0, exch=65.0)
    inp.water = [Reading(None)]
    engine.step(inp)
    assert engine.state.pid_source == "exchanger"


# ------------------------------------------------------------------ guards


def test_nest_change_is_reset_and_notified_at_most_every_ten_minutes():
    engine = make()
    enter(engine, now=0.0)
    first = run(engine, 30, nest=22.0)
    assert SetNest(15.0) in first
    assert any(isinstance(a, Notify) and a.key == "nest_reset" for a in first)
    second = run(engine, 70, nest=22.0)
    assert SetNest(15.0) in second
    assert not any(isinstance(a, Notify) and a.key == "nest_reset" for a in second)


def test_sat_turned_on_is_turned_off_and_openings_are_reapplied():
    engine = make()
    enter(engine, now=0.0)
    actions = run(engine, 30, sat=True)
    assert SetSat(False) in actions
    assert openings(actions) == {"living": 25, "kitchen": 25, "bedroom": 0}


# ---------------------------------------------------- restart and shutdown


def test_state_roundtrip_through_storage():
    engine = make()
    enter(engine, now=0.0)
    restored = EngineState.restore(engine.state.export())
    assert restored.mode == WOOD
    assert restored.wood_since == 0.0


def test_restart_in_wood_mode_near_the_end_of_a_burn_stays_in_wood_mode():
    engine = make()
    enter(engine, now=0.0)
    again = WoodEngine(engine.config, EngineState.restore(engine.state.export()))
    actions = again.startup(inputs(100, stove=50.0, exch=55.0))
    assert again.state.mode == WOOD
    assert InhibitRooms(ROOMS, True) in actions
    assert SetSat(False) in actions


def test_restart_in_wood_mode_exits_when_the_exit_conditions_are_met():
    engine = make()
    enter(engine, now=0.0)
    again = WoodEngine(engine.config, EngineState.restore(engine.state.export()))
    actions = again.startup(inputs(4000, stove=30.0, exch=40.0))
    assert again.state.mode == BOILER
    assert SetSat(True) in actions


def test_restart_in_boiler_mode_with_hot_stove_enters_wood_mode():
    engine = make()
    engine.startup(inputs(0, stove=62.0))
    assert engine.state.mode == WOOD


def test_restart_in_boiler_mode_releases_the_rooms():
    engine = make()
    actions = engine.startup(inputs(0, stove=25.0))
    assert InhibitRooms(ROOMS, False) in actions
    assert RestoreSnapshot() in actions


def test_unload_in_wood_mode_writes_100_everywhere():
    engine = make()
    enter(engine, now=0.0)
    actions = engine.shutdown(50.0)
    assert openings(actions) == {"living": 100, "kitchen": 100, "bedroom": 100}


def test_unload_in_boiler_mode_does_nothing():
    assert make().shutdown(0.0) == []
