from custom_components.wood_stove_mode.readings import Reading, evaluate_group, is_failed


def test_highest_reading_wins():
    result = evaluate_group([Reading(58.0), Reading(61.5)])
    assert result.value == 61.5
    assert not result.any_failed


def test_difference_reported():
    assert evaluate_group([Reading(50.0), Reading(57.0)]).difference == 7.0


def test_unavailable_sensor_falls_back_to_the_other():
    result = evaluate_group([Reading(None), Reading(48.0)])
    assert result.value == 48.0
    assert result.failed == (True, False)
    assert result.difference is None


def test_stale_sensor_counts_as_failed():
    assert is_failed(Reading(50.0, age=301.0))
    assert not is_failed(Reading(50.0, age=299.0))


def test_out_of_range_counts_as_failed():
    assert is_failed(Reading(-1.0))
    assert is_failed(Reading(110.5))
    assert not is_failed(Reading(0.0))
    assert not is_failed(Reading(110.0))


def test_all_failed():
    result = evaluate_group([Reading(None), Reading(200.0)])
    assert result.all_failed
    assert result.value is None
