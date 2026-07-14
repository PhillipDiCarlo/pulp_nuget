"""
Parsing and normalization utilities for NuGet packages (.nupkg) and manifests (.nuspec).

Reference: https://learn.microsoft.com/en-us/nuget/reference/nuspec and the nuspec XSD in
the NuGet/NuGet.Client repository. Version normalization follows NuGetVersion semantics:
https://learn.microsoft.com/en-us/nuget/concepts/package-versioning
"""

import re
import zipfile
from gettext import gettext as _
from xml.etree import ElementTree


class InvalidNupkgError(Exception):
    """Raised when a file is not a valid NuGet package."""


class InvalidNuspecError(InvalidNupkgError):
    """Raised when a .nuspec manifest cannot be parsed."""


_VERSION_RE = re.compile(
    r"^(?P<numbers>\d+(?:\.\d+){0,3})(?:-(?P<prerelease>[0-9A-Za-z\-\.]+))?"
    r"(?:\+(?P<metadata>[0-9A-Za-z\-\.]+))?$"
)


def normalize_version(version):
    """
    Return the NuGet-normalized form of a version string.

    - leading zeroes are removed from numeric segments (1.01 -> 1.1)
    - missing minor/patch segments are zero-filled (1.0 -> 1.0.0)
    - a zero fourth (revision) segment is omitted (1.0.0.0 -> 1.0.0)
    - the prerelease label is preserved, build metadata (+...) is dropped

    Raises InvalidNuspecError for unparsable versions.
    """
    match = _VERSION_RE.match(version.strip())
    if not match:
        raise InvalidNuspecError(_("Invalid NuGet version string: {}").format(version))
    numbers = [int(n) for n in match.group("numbers").split(".")]
    while len(numbers) < 3:
        numbers.append(0)
    if len(numbers) == 4 and numbers[3] == 0:
        numbers = numbers[:3]
    normalized = ".".join(str(n) for n in numbers)
    if match.group("prerelease"):
        normalized += "-" + match.group("prerelease")
    return normalized


def canonical_version(version):
    """The lowercased normalized version, as used in URLs and as natural key."""
    return normalize_version(version).lower()


def version_sort_key(version):
    """
    A sort key ordering versions by NuGet/SemVer2 precedence.

    Numeric segments compare numerically, a prerelease sorts before its release, and
    prerelease identifiers compare per SemVer rules (numeric identifiers numerically and
    lower than alphanumeric ones).
    """
    match = _VERSION_RE.match(version.strip())
    if not match:
        # Sort unparsable versions first; never raise from a sort.
        return ((-1, -1, -1, -1), (0, ()))
    numbers = [int(n) for n in match.group("numbers").split(".")]
    numbers += [0] * (4 - len(numbers))
    prerelease = match.group("prerelease")
    if prerelease is None:
        prerelease_key = (1, ())
    else:
        identifiers = tuple(
            (0, int(part), "") if part.isdigit() else (1, 0, part)
            for part in prerelease.lower().split(".")
        )
        prerelease_key = (0, identifiers)
    return (tuple(numbers), prerelease_key)


def _local_name(element):
    """Tag name of an element with any XML namespace stripped."""
    return element.tag.rsplit("}", 1)[-1]


def _find_child(element, name):
    for child in element:
        if _local_name(child) == name:
            return child
    return None


def _parse_dependencies(dependencies_element):
    """
    Normalize <dependencies> into a list of dependency groups.

    Both the flat form (plain <dependency> children) and the grouped form
    (<group targetFramework="...">) are supported. The flat form maps to a single
    group with a null targetFramework.
    """

    def parse_entry(dependency):
        entry = {"id": dependency.get("id")}
        if dependency.get("version"):
            entry["range"] = dependency.get("version")
        for attr in ("include", "exclude"):
            if dependency.get(attr):
                entry[attr] = dependency.get(attr)
        return entry

    groups = []
    flat_entries = []
    for child in dependencies_element:
        name = _local_name(child)
        if name == "group":
            groups.append(
                {
                    "targetFramework": child.get("targetFramework"),
                    "dependencies": [
                        parse_entry(dep) for dep in child if _local_name(dep) == "dependency"
                    ],
                }
            )
        elif name == "dependency":
            flat_entries.append(parse_entry(child))
    if flat_entries:
        groups.insert(0, {"targetFramework": None, "dependencies": flat_entries})
    return groups


def parse_nuspec(xml_data):
    """
    Parse .nuspec XML (bytes or str) and return a dict of package metadata.

    The parser is namespace-agnostic because multiple nuspec schema namespace
    versions exist in the wild.
    """
    try:
        root = ElementTree.fromstring(xml_data)
    except ElementTree.ParseError as exc:
        raise InvalidNuspecError(_("Malformed .nuspec XML: {}").format(exc))

    if _local_name(root) != "package":
        raise InvalidNuspecError(_("Unexpected root element: {}").format(root.tag))
    metadata = _find_child(root, "metadata")
    if metadata is None:
        raise InvalidNuspecError(_("The .nuspec has no <metadata> element."))

    simple_fields = {}
    for name in (
        "id",
        "version",
        "authors",
        "description",
        "title",
        "summary",
        "tags",
        "projectUrl",
        "licenseUrl",
        "iconUrl",
    ):
        element = _find_child(metadata, name)
        if element is not None and element.text is not None:
            simple_fields[name] = element.text.strip()

    package_id = simple_fields.get("id")
    version = simple_fields.get("version")
    if not package_id or not version:
        raise InvalidNuspecError(_("The .nuspec is missing required id or version."))

    license_expression = ""
    license_file = ""
    license_element = _find_child(metadata, "license")
    if license_element is not None and license_element.text:
        if license_element.get("type") == "file":
            license_file = license_element.text.strip()
        else:
            license_expression = license_element.text.strip()

    require_license_acceptance = False
    rla_element = _find_child(metadata, "requireLicenseAcceptance")
    if rla_element is not None and rla_element.text:
        require_license_acceptance = rla_element.text.strip().lower() == "true"

    dependencies_element = _find_child(metadata, "dependencies")
    dependency_groups = (
        _parse_dependencies(dependencies_element) if dependencies_element is not None else []
    )

    return {
        "package_id": package_id,
        "version": version,
        "version_normalized": canonical_version(version),
        "authors": simple_fields.get("authors", ""),
        "description": simple_fields.get("description", ""),
        "title": simple_fields.get("title", ""),
        "summary": simple_fields.get("summary", ""),
        "tags": simple_fields.get("tags", ""),
        "project_url": simple_fields.get("projectUrl", ""),
        "icon_url": simple_fields.get("iconUrl", ""),
        "license_expression": license_expression,
        "license_file": license_file,
        "license_url": simple_fields.get("licenseUrl", ""),
        "require_license_acceptance": require_license_acceptance,
        "min_client_version": metadata.get("minClientVersion", ""),
        "dependency_groups": dependency_groups,
    }


def parse_nupkg(file_or_path):
    """
    Extract and parse the .nuspec manifest from a .nupkg file (path or file object).

    The manifest must live in the root of the zip archive.
    """
    try:
        archive = zipfile.ZipFile(file_or_path)
    except zipfile.BadZipFile:
        raise InvalidNupkgError(_("The file is not a zip archive."))
    with archive:
        nuspec_names = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".nuspec") and "/" not in name
        ]
        if len(nuspec_names) != 1:
            raise InvalidNupkgError(
                _("Expected exactly one root-level .nuspec, found {}.").format(len(nuspec_names))
            )
        return parse_nuspec(archive.read(nuspec_names[0]))
