"""Unit tests for the .nupkg/.nuspec parser. Pure python, no database needed."""

import os

import pytest

from pulp_nuget.app.nuspec import (
    InvalidNupkgError,
    InvalidNuspecError,
    canonical_version,
    is_semver2,
    normalize_version,
    parse_nupkg,
    parse_nuspec,
    read_nuspec,
    read_package_file,
)

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
NEWTONSOFT_NUPKG = os.path.join(ASSETS_DIR, "newtonsoft.json.13.0.3.nupkg")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.0", "1.0.0"),
        ("1.0.0", "1.0.0"),
        ("1.01.1", "1.1.1"),
        ("1.00.0.0", "1.0.0"),
        ("1.0.0.5", "1.0.0.5"),
        ("1.0.0-Beta.1", "1.0.0-Beta.1"),
        ("1.0.0-beta+meta.data", "1.0.0-beta"),
        ("13.0.3", "13.0.3"),
        (" 2.1 ", "2.1.0"),
    ],
)
def test_normalize_version(raw, expected):
    assert normalize_version(raw) == expected


def test_canonical_version_is_lowercase():
    assert canonical_version("1.0.0-Beta.1") == "1.0.0-beta.1"


@pytest.mark.parametrize("raw", ["", "abc", "1.2.3.4.5", "1.0.0-***"])
def test_normalize_version_rejects_garbage(raw):
    with pytest.raises(InvalidNuspecError):
        normalize_version(raw)


def test_parse_newtonsoft_nupkg():
    metadata = parse_nupkg(NEWTONSOFT_NUPKG)
    assert metadata["package_id"] == "Newtonsoft.Json"
    assert metadata["version"] == "13.0.3"
    assert metadata["version_normalized"] == "13.0.3"
    assert metadata["authors"] == "James Newton-King"
    assert metadata["title"] == "Json.NET"
    assert metadata["tags"] == "json"
    assert metadata["license_expression"] == "MIT"
    assert metadata["license_url"] == "https://licenses.nuget.org/MIT"
    assert metadata["project_url"] == "https://www.newtonsoft.com/json"
    assert metadata["min_client_version"] == "2.12"
    assert metadata["require_license_acceptance"] is False
    assert "high-performance JSON framework" in metadata["description"]

    groups = metadata["dependency_groups"]
    assert len(groups) == 8
    tfms = {group["targetFramework"] for group in groups}
    assert ".NETStandard2.0" in tfms
    assert "net6.0" in tfms
    netstandard13 = next(g for g in groups if g["targetFramework"] == ".NETStandard1.3")
    assert {
        "id": "Microsoft.CSharp",
        "range": "4.3.0",
        "exclude": "Build,Analyzers",
    } in netstandard13["dependencies"]
    empty_group = next(g for g in groups if g["targetFramework"] == ".NETFramework2.0")
    assert empty_group["dependencies"] == []


def test_parse_nuspec_flat_dependencies():
    xml = b"""<?xml version="1.0"?>
    <package xmlns="http://schemas.microsoft.com/packaging/2010/07/nuspec.xsd">
      <metadata>
        <id>Flat.Package</id>
        <version>1.0.0-RC.1+build5</version>
        <authors>a, b</authors>
        <description>desc</description>
        <dependencies>
          <dependency id="Dep.One" version="[1.0,2.0)" />
        </dependencies>
      </metadata>
    </package>"""
    metadata = parse_nuspec(xml)
    assert metadata["package_id"] == "Flat.Package"
    assert metadata["version"] == "1.0.0-RC.1+build5"
    assert metadata["version_normalized"] == "1.0.0-rc.1"
    assert metadata["dependency_groups"] == [
        {
            "targetFramework": None,
            "dependencies": [{"id": "Dep.One", "range": "[1.0,2.0)"}],
        }
    ]


def test_parse_nuspec_license_file():
    xml = b"""<package><metadata>
        <id>X</id><version>1.0</version>
        <license type="file">LICENSE.txt</license>
    </metadata></package>"""
    metadata = parse_nuspec(xml)
    assert metadata["license_file"] == "LICENSE.txt"
    assert metadata["license_expression"] == ""


def test_parse_nuspec_embedded_icon_and_readme():
    xml = b"""<package><metadata>
        <id>X</id><version>1.0</version>
        <icon>images\\icon.png</icon>
        <readme>docs/README.md</readme>
    </metadata></package>"""
    metadata = parse_nuspec(xml)
    # Backslash paths are normalized to the forward slashes zip archives use.
    assert metadata["icon_file"] == "images/icon.png"
    assert metadata["readme_file"] == "docs/README.md"


def test_parse_nuspec_no_embedded_assets():
    xml = b"<package><metadata><id>X</id><version>1.0</version></metadata></package>"
    metadata = parse_nuspec(xml)
    assert metadata["icon_file"] == ""
    assert metadata["readme_file"] == ""


def test_read_package_file(tmp_path):
    import zipfile

    path = tmp_path / "pkg.nupkg"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("docs/README.md", b"# hello")
    assert read_package_file(str(path), "docs/README.md") == b"# hello"
    # Case-insensitive fallback: the nuspec declaration may not match the entry casing.
    assert read_package_file(str(path), "Docs/readme.MD") == b"# hello"
    assert read_package_file(str(path), "missing.txt") is None


def test_parse_nuspec_missing_id():
    with pytest.raises(InvalidNuspecError):
        parse_nuspec(b"<package><metadata><version>1.0</version></metadata></package>")


def test_parse_nupkg_not_a_zip(tmp_path):
    bogus = tmp_path / "bogus.nupkg"
    bogus.write_bytes(b"not a zip")
    with pytest.raises(InvalidNupkgError):
        parse_nupkg(str(bogus))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.0.0", False),
        ("1.0.0-beta", False),
        ("1.0.0-beta.1", True),
        ("1.0.0+build5", True),
        ("1.0.0-rc.1+build5", True),
        ("garbage", False),
    ],
)
def test_is_semver2(raw, expected):
    assert is_semver2(raw) is expected


def test_parse_nuspec_package_types():
    xml = b"""<package><metadata>
        <id>X</id><version>1.0</version>
        <packageTypes>
          <packageType name="DotnetTool" />
          <packageType name="Custom" version="2.0" />
        </packageTypes>
    </metadata></package>"""
    metadata = parse_nuspec(xml)
    assert metadata["package_types"] == [
        {"name": "DotnetTool"},
        {"name": "Custom", "version": "2.0"},
    ]


def test_parse_nuspec_no_package_types():
    xml = b"<package><metadata><id>X</id><version>1.0</version></metadata></package>"
    assert parse_nuspec(xml)["package_types"] == []


def test_read_nuspec_returns_raw_xml():
    xml = read_nuspec(NEWTONSOFT_NUPKG)
    assert b"<id>Newtonsoft.Json</id>" in xml
    assert parse_nuspec(xml)["version"] == "13.0.3"
