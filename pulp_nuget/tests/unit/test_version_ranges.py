"""Tests for NuGet version-range parsing and matching."""

import pytest

from pulp_nuget.app.nuspec import (
    InvalidVersionRangeError,
    parse_package_filter,
    parse_version_range,
)


def test_bare_version_is_inclusive_minimum():
    version_range = parse_version_range("1.0")
    assert version_range.contains("1.0")
    assert version_range.contains("1.0.0")
    assert version_range.contains("99.0")
    assert not version_range.contains("0.9")
    assert not version_range.contains("1.0.0-beta")  # prerelease sorts below the release


def test_exact_version():
    version_range = parse_version_range("[13.0.2]")
    assert version_range.contains("13.0.2")
    assert version_range.contains("13.0.2.0")  # zero revision is the same version
    assert not version_range.contains("13.0.1")
    assert not version_range.contains("13.0.3")


def test_closed_and_half_open_intervals():
    closed = parse_version_range("[1.0,2.0]")
    assert closed.contains("1.0") and closed.contains("2.0") and closed.contains("1.5")
    assert not closed.contains("2.0.1")

    half_open = parse_version_range("[1.0,2.0)")
    assert half_open.contains("1.0") and half_open.contains("1.9.9")
    assert not half_open.contains("2.0")

    open_range = parse_version_range("(1.0,2.0)")
    assert not open_range.contains("1.0")
    assert open_range.contains("1.0.1")


def test_unbounded_sides():
    minimum_exclusive = parse_version_range("(1.0,)")
    assert not minimum_exclusive.contains("1.0")
    assert minimum_exclusive.contains("1.0.1")

    maximum_only = parse_version_range("(,2.0]")
    assert maximum_only.contains("0.1") and maximum_only.contains("2.0")
    assert not maximum_only.contains("2.0.1")

    everything = parse_version_range("(,)")
    assert everything.contains("0.0.1") and everything.contains("100.0")


def test_prerelease_and_metadata_semantics():
    version_range = parse_version_range("[1.0.0-beta,1.0.0]")
    assert version_range.contains("1.0.0-BETA")  # prerelease compares case-insensitively
    assert version_range.contains("1.0.0-rc.1")
    assert version_range.contains("1.0.0+build5")  # build metadata is ignored
    assert not version_range.contains("1.0.0-alpha")
    assert not version_range.contains("1.0.1")


def test_include_matching_skips_prereleases_for_stable_ranges():
    stable = parse_version_range("[1.0.1, 1.0.2]")
    assert stable.matches_for_include("1.0.1")
    assert stable.matches_for_include("1.0.2")
    # 1.0.2-beta1 is inside the window by precedence, but the bounds are stable.
    assert stable.contains("1.0.2-beta1")
    assert not stable.matches_for_include("1.0.2-beta1")

    opted_in = parse_version_range("[1.0.1-alpha, 1.0.2]")
    assert opted_in.matches_for_include("1.0.2-beta1")


def test_bound_helpers():
    version_range = parse_version_range("[1.5,2.0)")
    # A registration page covering [1.0, 1.4] cannot intersect the range.
    assert version_range.excludes_all_below("1.4")
    assert not version_range.excludes_all_below("1.5")
    # A page covering [2.0, 3.0] cannot intersect it either (2.0 is excluded).
    assert version_range.excludes_all_above("2.0")
    assert not version_range.excludes_all_above("1.9")


@pytest.mark.parametrize(
    "invalid",
    ["", "  ", "(1.0)", "[,]", "[1.0", "1.0]", "[a.b.c]", "[2.0,1.0]", "[1.0,2.0,3.0]", "[]"],
)
def test_invalid_ranges_raise(invalid):
    with pytest.raises(InvalidVersionRangeError):
        parse_version_range(invalid)


def test_package_filter_plain_id():
    package_id, version_range = parse_package_filter("Serilog")
    assert package_id == "serilog"
    assert version_range is None


def test_package_filter_with_range():
    package_id, version_range = parse_package_filter("Newtonsoft.Json [13.0.1, 13.0.2]")
    assert package_id == "newtonsoft.json"
    assert version_range.contains("13.0.1")
    assert not version_range.contains("13.0.3")


def test_package_filter_with_bare_minimum():
    package_id, version_range = parse_package_filter("Serilog 2.0")
    assert package_id == "serilog"
    assert version_range.contains("3.0")
    assert not version_range.contains("1.9")


@pytest.mark.parametrize("invalid", ["", "Serilog[2.0,)", "Serilog (bad", "Serilog 2.0 extra"])
def test_invalid_package_filters_raise(invalid):
    with pytest.raises(InvalidVersionRangeError):
        parse_package_filter(invalid)
