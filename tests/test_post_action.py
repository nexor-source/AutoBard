from autobard.tracking import PostActionTrajectoryVerifier


def test_post_action_reanchor_uses_observed_path_instead_of_nominal_note() -> None:
    verifier = PostActionTrajectoryVerifier(
        action_timestamp=10.0,
        expected_x=201.0,
        note_target=208.5,
        speed=108.644,
        input_latency_s=0.045,
        required_samples=3,
    )

    assert verifier.observe(10.032, 205.0) is None
    assert verifier.observe(10.049, 207.5) is None
    result = verifier.observe(10.067, 208.5)

    assert result is not None
    assert result.sample_count == 3
    assert 208.5 <= result.x <= 210.0


def test_post_action_reanchor_also_follows_a_missed_click_continuation() -> None:
    verifier = PostActionTrajectoryVerifier(
        action_timestamp=20.0,
        expected_x=260.0,
        note_target=273.0,
        speed=176.0,
        input_latency_s=0.045,
        required_samples=3,
    )

    verifier.observe(20.02, 263.5)
    verifier.observe(20.04, 267.0)
    result = verifier.observe(20.06, 270.5)

    assert result is not None
    assert result.outcome == "continuous"
    assert abs(result.x - 270.5) < 0.2
