from custom_components.wood_stove_mode.pid import Pid


def test_proportional_only():
    pid = Pid(kp=2.0, ki=0.0, kd=0.0)
    pid.preset(0.0)
    assert pid.update(10.0, now=0.0) == 20.0


def test_output_is_clamped():
    pid = Pid(kp=10.0, ki=0.0, kd=0.0)
    pid.preset(0.0)
    assert pid.update(50.0, now=0.0) == 100.0
    assert pid.update(-50.0, now=1.0) == 0.0


def test_preset_is_bumpless():
    pid = Pid(kp=4.0, ki=0.01, kd=0.0)
    pid.preset(25.0, error=3.0)
    assert pid.update(3.0, now=0.0) == 25.0


def test_integral_accumulates():
    pid = Pid(kp=0.0, ki=0.1, kd=0.0)
    pid.preset(10.0)
    pid.update(5.0, now=0.0)
    assert pid.update(5.0, now=10.0) == 10.0 + 0.1 * 5.0 * 10.0


def test_no_windup_when_saturated():
    pid = Pid(kp=0.0, ki=1.0, kd=0.0)
    pid.preset(95.0)
    pid.update(10.0, now=0.0)
    for t in range(1, 50):
        assert pid.update(10.0, now=float(t)) == 100.0
    # Once the error flips, the output leaves saturation at once.
    assert pid.update(-10.0, now=60.0) < 100.0


def test_freeze_integral():
    pid = Pid(kp=0.0, ki=1.0, kd=0.0)
    pid.preset(10.0)
    pid.update(1.0, now=0.0)
    assert pid.update(1.0, now=10.0, freeze_integral=True) == 10.0


def test_export_restore_roundtrip():
    pid = Pid(kp=1.0, ki=0.5, kd=0.0)
    pid.preset(20.0)
    pid.update(2.0, now=0.0)
    pid.update(2.0, now=4.0)
    other = Pid(kp=1.0, ki=0.5, kd=0.0)
    other.restore(pid.export())
    assert other.update(2.0, now=8.0) == pid.update(2.0, now=8.0)
