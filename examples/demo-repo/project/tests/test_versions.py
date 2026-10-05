from releasekit.versions import is_newer, latest, parse_version


def test_parse_version_accepts_v_prefix():
    assert parse_version("v1.4.2") == (1, 4, 2)


def test_is_newer_simple():
    assert is_newer("1.2.0", "1.1.9")
    assert not is_newer("1.1.9", "1.2.0")


def test_is_newer_handles_double_digit_minor():
    assert is_newer("1.10.0", "1.9.0")


def test_latest_picks_highest_release():
    assert latest(["1.9.0", "1.10.0", "1.2.3"]) == "1.10.0"
