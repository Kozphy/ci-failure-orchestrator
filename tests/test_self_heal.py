from scripts.self_heal_github import decide


def test_network_failure_is_eligible_for_one_bounded_rerun():
    result = decide("connection reset by peer while downloading dependency")
    assert result["error_type"] == "NETWORK_ERROR"
    assert result["action"] == "RERUN_FAILED"


def test_flaky_timeout_is_eligible_for_one_bounded_rerun():
    result = decide("test timed out and is known intermittent")
    assert result["error_type"] == "FLAKY_TEST"
    assert result["action"] == "RERUN_FAILED"


def test_assertion_failure_requires_repair_path():
    result = decide("AssertionError: expected 2 got 3")
    assert result["error_type"] == "TEST_ASSERTION"
    assert result["action"] == "ESCALATE_REPAIR"


def test_unknown_failure_fails_closed_to_repair_path():
    result = decide("mysterious runner failure")
    assert result["error_type"] == "UNKNOWN"
    assert result["action"] == "ESCALATE_REPAIR"
