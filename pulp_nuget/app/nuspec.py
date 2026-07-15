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


def is_semver2(version):
    """
    Whether a version string requires SemVer 2.0.0 support in the client.

    A version is SemVer2 if it has build metadata (+...) or a dot-separated prerelease
    label (e.g. 1.0.0-beta.1). Such packages are hidden from clients that do not send
    semVerLevel=2.0.0. Unparsable versions are treated as not SemVer2.
    """
    match = _VERSION_RE.match(version.strip())
    if not match:
        return False
    if match.group("metadata"):
        return True
    prerelease = match.group("prerelease")
    return bool(prerelease and "." in prerelease)


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


class InvalidVersionRangeError(ValueError):
    """Raised when a NuGet version range or package filter cannot be parsed."""


def is_prerelease(version):
    """Whether a version string carries a prerelease label (1.0.0-beta). Unparsable: False."""
    match = _VERSION_RE.match(version.strip())
    return bool(match and match.group("prerelease"))


class VersionRange:
    """
    A NuGet version range in bracket notation.

    https://learn.microsoft.com/en-us/nuget/concepts/package-versioning#version-ranges
    Bounds compare by NuGet/SemVer2 precedence, so build metadata is ignored and
    prerelease labels compare case-insensitively.
    """

    def __init__(self, min_version, min_inclusive, max_version, max_inclusive, raw):
        self.min_version = min_version
        self.min_inclusive = min_inclusive
        self.max_version = max_version
        self.max_inclusive = max_inclusive
        self.raw = raw
        self._min_key = version_sort_key(min_version) if min_version else None
        self._max_key = version_sort_key(max_version) if max_version else None
        self.has_prerelease_bound = bool(
            (min_version and is_prerelease(min_version))
            or (max_version and is_prerelease(max_version))
        )

    def __repr__(self):
        return f"VersionRange({self.raw!r})"

    def contains(self, version):
        """Whether a version string falls inside the range, by pure precedence."""
        key = version_sort_key(version)
        if self._min_key is not None:
            if key < self._min_key or (key == self._min_key and not self.min_inclusive):
                return False
        if self._max_key is not None:
            if key > self._max_key or (key == self._max_key and not self.max_inclusive):
                return False
        return True

    def matches_for_include(self, version):
        """
        contains(), but prerelease versions only match when a bound is prerelease.

        This follows NuGet's user-facing convention: ``[1.0,2.0]`` selects stable
        versions only, while ``[1.0-alpha,2.0]`` opts prereleases in.
        """
        if not self.contains(version):
            return False
        return not is_prerelease(version) or self.has_prerelease_bound

    def excludes_all_below(self, version):
        """Whether every version <= the given one is outside the range."""
        if self._min_key is None:
            return False
        key = version_sort_key(version)
        return key < self._min_key or (key == self._min_key and not self.min_inclusive)

    def excludes_all_above(self, version):
        """Whether every version >= the given one is outside the range."""
        if self._max_key is None:
            return False
        key = version_sort_key(version)
        return key > self._max_key or (key == self._max_key and not self.max_inclusive)


def _require_version(text, range_string):
    if not _VERSION_RE.match(text):
        raise InvalidVersionRangeError(
            _("Invalid version '{}' in version range '{}'.").format(text, range_string)
        )
    return text


def parse_version_range(range_string):
    """
    Parse a NuGet version range into a VersionRange.

    Accepted forms: ``1.0`` (minimum, inclusive), ``[1.0]`` (exact), and interval
    notation like ``[1.0,2.0)``, ``(1.0,)``, or ``(,2.0]``. ``(,)`` matches everything.
    """
    text = range_string.strip()
    if not text:
        raise InvalidVersionRangeError(_("Empty version range."))
    if text[0] not in "[(":
        # A bare version means "this version or higher", like a plain nuspec dependency.
        return VersionRange(_require_version(text, text), True, None, False, raw=text)
    if len(text) < 2 or text[-1] not in "])":
        raise InvalidVersionRangeError(
            _("Version range '{}' does not end with ')' or ']'.").format(text)
        )
    min_inclusive = text[0] == "["
    max_inclusive = text[-1] == "]"
    parts = [part.strip() for part in text[1:-1].split(",")]
    if len(parts) == 1:
        # An exact version requires inclusive brackets: [1.0]. (1.0) matches nothing.
        if not (min_inclusive and max_inclusive and parts[0]):
            raise InvalidVersionRangeError(
                _("Version range '{}' is not a valid exact-version range.").format(text)
            )
        version = _require_version(parts[0], text)
        return VersionRange(version, True, version, True, raw=text)
    if len(parts) != 2:
        raise InvalidVersionRangeError(_("Invalid version range '{}'.").format(text))
    lower, upper = parts
    if not lower and not upper and (min_inclusive or max_inclusive):
        raise InvalidVersionRangeError(
            _("Version range '{}' has inclusive brackets but no bounds.").format(text)
        )
    lower = _require_version(lower, text) if lower else None
    upper = _require_version(upper, text) if upper else None
    if lower and upper and version_sort_key(lower) > version_sort_key(upper):
        raise InvalidVersionRangeError(
            _("Version range '{}' has a lower bound above its upper bound.").format(text)
        )
    return VersionRange(lower, min_inclusive, upper, max_inclusive, raw=text)


def parse_package_filter(entry):
    """
    Parse a remote includes/excludes entry into (package_id_lower, VersionRange or None).

    An entry is a package id, optionally followed by whitespace and a version range:
    ``"Serilog"``, ``"Serilog [2.0,3.0)"``, ``"Serilog (,2.0]"``, ``"Serilog 2.0"``.
    """
    parts = entry.strip().split(None, 1)
    if not parts:
        raise InvalidVersionRangeError(_("Empty package filter entry."))
    package_id = parts[0]
    if any(character in package_id for character in "[](),"):
        raise InvalidVersionRangeError(
            _(
                "Invalid package filter '{}': separate the package id and the version "
                "range with a space, e.g. 'Serilog [2.0,3.0)'."
            ).format(entry)
        )
    version_range = parse_version_range(parts[1]) if len(parts) == 2 else None
    return package_id.lower(), version_range


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

    package_types = []
    package_types_element = _find_child(metadata, "packageTypes")
    if package_types_element is not None:
        for child in package_types_element:
            if _local_name(child) == "packageType" and child.get("name"):
                entry = {"name": child.get("name")}
                if child.get("version"):
                    entry["version"] = child.get("version")
                package_types.append(entry)

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
        "package_types": package_types,
    }


def read_nuspec(file_or_path):
    """
    Return the raw .nuspec XML bytes from a .nupkg file (path or file object).

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
        return archive.read(nuspec_names[0])


def parse_nupkg(file_or_path):
    """
    Extract and parse the .nuspec manifest from a .nupkg file (path or file object).
    """
    return parse_nuspec(read_nuspec(file_or_path))
