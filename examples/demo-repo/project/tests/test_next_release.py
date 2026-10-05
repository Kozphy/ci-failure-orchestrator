import pytest

from releasekit.versions import next_release


@pytest.mark.parametrize(
    ("part", "expected"),
    [("major", "2.0.0"), ("minor", "1.5.0"), ("patch", "1.4.3")],
)
def test_next_release(part, expected):
    assert next_release("1.4.2", part) == expected


def test_next_release_rejects_unknown_part():
    with pytest.raises(ValueError):
        next_release("1.4.2", "build")
