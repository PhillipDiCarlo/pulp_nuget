"""Unit tests for the package retention helper."""

from pulp_nuget.app.models import retention_surplus


def test_retention_keeps_newest_by_precedence():
    rows = [
        (1, "pkg", "1.0.0"),
        (2, "pkg", "2.0.0"),
        (3, "pkg", "10.0.0"),
        (4, "pkg", "2.0.0-beta.1"),
    ]
    # 10.0.0 and 2.0.0 rank highest; the prerelease sorts just below its release.
    assert sorted(retention_surplus(rows, 2)) == [1, 4]
    assert sorted(retention_surplus(rows, 3)) == [1]


def test_retention_is_per_package_id():
    rows = [
        (1, "a", "1.0.0"),
        (2, "a", "2.0.0"),
        (3, "b", "1.0.0"),
    ]
    assert retention_surplus(rows, 1) == [1]


def test_retention_with_room_to_spare():
    rows = [(1, "a", "1.0.0"), (2, "a", "2.0.0")]
    assert retention_surplus(rows, 2) == []
    assert retention_surplus(rows, 5) == []
    assert retention_surplus([], 1) == []
