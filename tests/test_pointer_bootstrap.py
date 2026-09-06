from autobard.models import PointerMeasurement
from autobard.tracking import PointerBootstrapper


CONFIG = {
    "bootstrap_confirm_frames": 4,
    "bootstrap_min_displacement_ratio": 0.003,
    "bootstrap_backward_tolerance_ratio": 0.004,
    "bootstrap_max_gap_ms": 80,
    "bootstrap_min_r_squared": 0.72,
    "min_speed_px_s": 20.0,
    "max_speed_px_s": 3000.0,
}


def measurement(x: float) -> PointerMeasurement:
    return PointerMeasurement(x=x, confidence=0.9, width=3.0)


def test_bootstrap_confirms_consecutive_rightward_motion() -> None:
    bootstrapper = PointerBootstrapper(CONFIG, frame_width=581)

    assert bootstrapper.update(1.000, measurement(120.0)) is None
    assert bootstrapper.update(1.016, measurement(126.0)) is None
    assert bootstrapper.update(1.032, measurement(132.0)) is None
    confirmed = bootstrapper.update(1.048, measurement(138.0))

    assert confirmed is not None
    assert [sample.measurement.x for sample in confirmed] == [120.0, 126.0, 132.0, 138.0]


def test_bootstrap_confirms_collected_slow_pointer_without_long_delay() -> None:
    bootstrapper = PointerBootstrapper(CONFIG, frame_width=581)

    for index, x in enumerate([127.5, 129.5, 131.0]):
        assert bootstrapper.update(1.0 + index * 0.018, measurement(x)) is None
    confirmed = bootstrapper.update(1.054, measurement(133.0))

    assert confirmed is not None
    assert abs(confirmed[-1].timestamp - confirmed[0].timestamp - 0.054) < 1e-9


def test_bootstrap_does_not_confirm_static_jitter() -> None:
    bootstrapper = PointerBootstrapper(CONFIG, frame_width=581)

    for index, x in enumerate([200.0, 200.5, 199.5, 201.0, 200.0, 201.5]):
        assert bootstrapper.update(1.0 + index * 0.016, measurement(x)) is None


def test_bootstrap_recovers_after_backward_animation() -> None:
    bootstrapper = PointerBootstrapper(CONFIG, frame_width=581)

    for index, x in enumerate([190.0, 178.0, 165.0]):
        assert bootstrapper.update(1.0 + index * 0.016, measurement(x)) is None

    assert bootstrapper.update(1.060, measurement(120.0)) is None
    assert bootstrapper.update(1.076, measurement(127.0)) is None
    assert bootstrapper.update(1.092, measurement(134.0)) is None
    confirmed = bootstrapper.update(1.108, measurement(141.0))

    assert confirmed is not None
