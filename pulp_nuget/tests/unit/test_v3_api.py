"""Unit tests for the v3 API builders: routing regexes and registration paging."""

from types import SimpleNamespace

from pulp_nuget.app import v3_api


def _stub(version, **overrides):
    """A NugetPackageContent stand-in with every field _catalog_entry touches."""
    fields = dict(
        package_id="Test.Pkg",
        package_id_lower="test.pkg",
        version=version,
        version_normalized=version,
        authors="",
        description="",
        title="",
        summary="",
        tags="",
        project_url="",
        icon_url="",
        license_expression="",
        license_url="",
        require_license_acceptance=False,
        min_client_version="",
        dependency_groups=[],
        package_types=[],
        listed=True,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


BASE = "http://example.test/pulp/content/feed/"


def test_flatcontainer_re_matches_nupkg_and_nuspec():
    match = v3_api.FLATCONTAINER_RE.match("v3-flatcontainer/test.pkg/1.0.0/test.pkg.1.0.0.nupkg")
    assert match and match["filename"] == "test.pkg.1.0.0.nupkg"
    match = v3_api.FLATCONTAINER_RE.match("v3-flatcontainer/test.pkg/1.0.0/test.pkg.nuspec")
    assert match and match["filename"] == "test.pkg.nuspec"
    assert v3_api.FLATCONTAINER_RE.match("v3-flatcontainer/test.pkg/1.0.0/readme.md") is None


def test_registration_page_re():
    match = v3_api.REGISTRATION_PAGE_RE.match(
        "v3/registrations/test.pkg/page/1.0.0/2.0.0-beta.json"
    )
    assert match["package_id"] == "test.pkg"
    assert match["lower"] == "1.0.0"
    assert match["upper"] == "2.0.0-beta"
    assert v3_api.REGISTRATION_RE.match("v3/registrations/test.pkg/page/1.0.0/2.0.0.json") is None


def test_page_chunks():
    packages = [_stub(f"1.0.{i}") for i in range(130)]
    chunks = v3_api._page_chunks(packages, 64)
    assert [len(chunk) for chunk in chunks] == [64, 64, 2]
    assert chunks[0][0].version_normalized == "1.0.0"
    assert chunks[2][-1].version_normalized == "1.0.129"
    assert v3_api._page_chunks(packages[:5], 64) == [packages[:5]]


def test_full_page_shape():
    packages = [_stub("1.0.0"), _stub("1.0.1", listed=False)]
    page_id = v3_api._page_url(BASE, "test.pkg", packages)
    page = v3_api._full_page(packages, BASE, "test.pkg", page_id)
    assert page["@id"] == BASE + "v3/registrations/test.pkg/page/1.0.0/1.0.1.json"
    assert page["@type"] == "catalog:CatalogPage"
    assert page["count"] == 2
    assert page["lower"] == "1.0.0"
    assert page["upper"] == "1.0.1"
    assert page["parent"] == BASE + "v3/registrations/test.pkg/index.json"
    leaves = page["items"]
    assert [leaf["catalogEntry"]["version"] for leaf in leaves] == ["1.0.0", "1.0.1"]
    assert [leaf["listed"] for leaf in leaves] == [True, False]
    assert [leaf["catalogEntry"]["listed"] for leaf in leaves] == [True, False]


def test_package_type_names():
    assert v3_api._package_type_names(_stub("1.0.0")) == ["Dependency"]
    stub = _stub("1.0.0", package_types=[{"name": "DotnetTool"}, {"name": "Custom"}])
    assert v3_api._package_type_names(stub) == ["DotnetTool", "Custom"]
