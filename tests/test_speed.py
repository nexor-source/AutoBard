from autobard.tracking.speed import RobustSpeedEstimator


def test_robust_speed_with_outlier() -> None:
    estimator = RobustSpeedEstimator(history_size=20, min_samples=4)
    for index in range(10):
        x = 25.0 + 180.0 * index * 0.01
        if index == 6:
            x += 25.0
        estimator.add(10.0 + index * 0.01, x, 0.9)
    fit = estimator.fit()
    assert fit is not None
    assert abs(fit.speed - 180.0) < 18.0
