"""
Builders for the NuGet v3 API resources served by a NugetDistribution.

The JSON shapes mirror the resources served by api.nuget.org; when a client fails to
restore, diff our response against the equivalent api.nuget.org resource.

Endpoints (relative to a distribution's base URL):
- v3/index.json                                       service index
- v3-flatcontainer/{id}/index.json                    package versions (incl. unlisted)
- v3-flatcontainer/{id}/{version}/{id}.{version}.nupkg
- v3-flatcontainer/{id}/{version}/{id}.{version}.snupkg  symbol package, when one is stored
- v3-flatcontainer/{id}/{version}/{id}.nuspec         manifest (404 for on-demand packages
                                                      whose .nupkg was never fetched)
- v3-flatcontainer/{id}/{version}/icon                embedded icon (same 404 caveat; also
- v3-flatcontainer/{id}/{version}/readme              404 when the package embeds none)
- symbols/{file}.pdb/{signature}/{file}.pdb           SSQP symbol server: portable PDBs
                                                      extracted from stored .snupkg files
                                                      (point debuggers at <base>/symbols/)
- v3/registrations/{id}/index.json                    registration index; pages are inlined
                                                      up to REGISTRATION_PAGE_SIZE versions,
                                                      external beyond that
- v3/registrations/{id}/page/{lower}/{upper}.json     external registration page
- v3/registrations/{id}/{version}.json                registration leaf
- v3/search                                           SearchQueryService (query params, so it
                                                      is served by a content-app route, see
                                                      content.py)

SemVer2 note: every advertised registration hive serves the same URL and includes SemVer2
packages. Strictly, the plain RegistrationsBaseUrl hive should exclude them, but all
maintained clients prefer the 3.6.0/Versioned hives; search does honor semVerLevel.
"""

import re

from aiohttp import web
from django.conf import settings

from pulpcore.plugin.models import ContentArtifact

from pulp_nuget.app.nuspec import (
    InvalidNupkgError,
    is_semver2,
    read_nuspec,
    read_package_file,
    version_sort_key,
)

FLATCONTAINER_RE = re.compile(
    r"^v3-flatcontainer/(?P<package_id>[^/]+)/(?:index\.json$|(?P<version>[^/]+)/"
    r"(?P<filename>[^/]+\.(?:s?nupkg|nuspec)|icon|readme)$)"
)
# SSQP symbol request: <file>.pdb/<40 hex chars>/<file>.pdb. Keys are lowercase per the
# spec, but match case-insensitively and compare in code.
SYMBOLS_RE = re.compile(
    r"^symbols/(?P<filename>[^/]+\.pdb)/(?P<signature>[0-9a-f]{40})/(?P<filename2>[^/]+\.pdb)$",
    re.IGNORECASE,
)
REGISTRATION_RE = re.compile(
    r"^v3/registrations/(?P<package_id>[^/]+)/(?:index\.json$|(?P<version>[^/]+)\.json$)"
)
REGISTRATION_PAGE_RE = re.compile(
    r"^v3/registrations/(?P<package_id>[^/]+)/page/(?P<lower>[^/]+)/(?P<upper>[^/]+)\.json$"
)

# Maximum leaves inlined into a registration index / held by one external page.
# nuget.org uses 64. Overridable (e.g. in tests) via the Django setting of the same name.
REGISTRATION_PAGE_SIZE = 64


def _page_size():
    return getattr(settings, "NUGET_REGISTRATION_PAGE_SIZE", REGISTRATION_PAGE_SIZE)


def base_url(distribution):
    """The absolute base URL of this distribution, with a trailing slash."""
    origin = settings.CONTENT_ORIGIN.strip("/")
    prefix = settings.CONTENT_PATH_PREFIX.strip("/")
    parts = [origin, prefix]
    if settings.DOMAIN_ENABLED:
        parts.append(distribution.pulp_domain.name)
    parts.append(distribution.base_path.strip("/"))
    return "/".join(parts) + "/"


def _api_url(distribution, prefix):
    origin = settings.CONTENT_ORIGIN.strip("/")
    parts = [origin, prefix]
    if settings.DOMAIN_ENABLED:
        parts.append(distribution.pulp_domain.name)
    parts.append(distribution.base_path.strip("/"))
    return "/".join(parts)


def publish_url(distribution):
    """The absolute URL of the PackagePublish resource for this distribution."""
    return _api_url(distribution, "pulp_nuget/publish")


def symbol_publish_url(distribution):
    """The absolute URL of the SymbolPackagePublish resource for this distribution."""
    return _api_url(distribution, "pulp_nuget/publish-symbols")


def get_packages(distribution):
    """A queryset of the NugetPackageContent served by this distribution."""
    from pulp_nuget.app.models import NugetPackageContent

    _, repo_version, _ = distribution.get_repository_publication_and_version()
    if repo_version is None:
        return NugetPackageContent.objects.none()
    return NugetPackageContent.objects.filter(pk__in=repo_version.content)


def service_index(distribution):
    """The v3/index.json service index."""
    base = base_url(distribution)
    flatcontainer = base + "v3-flatcontainer/"
    registrations = base + "v3/registrations/"
    search = base + "v3/search"
    resources = [
        {
            "@id": flatcontainer,
            "@type": "PackageBaseAddress/3.0.0",
            "comment": "Base URL of where NuGet packages are stored, in the format "
            "https://.../v3-flatcontainer/{id-lower}/{version-lower}/"
            "{id-lower}.{version-lower}.nupkg",
        },
        {"@id": registrations, "@type": "RegistrationsBaseUrl"},
        {"@id": registrations, "@type": "RegistrationsBaseUrl/3.0.0-rc"},
        {"@id": registrations, "@type": "RegistrationsBaseUrl/3.0.0-beta"},
        {"@id": registrations, "@type": "RegistrationsBaseUrl/3.6.0"},
        {"@id": registrations, "@type": "RegistrationsBaseUrl/Versioned"},
        {"@id": search, "@type": "SearchQueryService"},
        {"@id": search, "@type": "SearchQueryService/3.0.0-rc"},
        {"@id": search, "@type": "SearchQueryService/3.0.0-beta"},
        {"@id": publish_url(distribution), "@type": "PackagePublish/2.0.0"},
        {"@id": symbol_publish_url(distribution), "@type": "SymbolPackagePublish/4.9.0"},
    ]
    return {"version": "3.0.0", "resources": resources}


def flatcontainer_versions(distribution, package_id_lower):
    """The v3-flatcontainer/{id}/index.json version list, or None if the id is unknown."""
    versions = list(
        get_packages(distribution)
        .filter(package_id_lower=package_id_lower)
        .values_list("version_normalized", flat=True)
    )
    if not versions:
        return None
    versions.sort(key=version_sort_key)
    return {"versions": versions}


def get_package_artifact(distribution, package_id_lower, version, filename):
    """The ContentArtifact for a flatcontainer .nupkg request, or None."""
    version = version.lower()
    if filename.lower() != f"{package_id_lower}.{version}.nupkg":
        return None
    package = (
        get_packages(distribution)
        .filter(package_id_lower=package_id_lower, version_normalized=version)
        .first()
    )
    if package is None:
        return None
    return ContentArtifact.objects.select_related("artifact").filter(content=package).first()


def get_symbol_packages(distribution):
    """A queryset of the NugetSymbolPackageContent served by this distribution."""
    from pulp_nuget.app.models import NugetSymbolPackageContent

    _, repo_version, _ = distribution.get_repository_publication_and_version()
    if repo_version is None:
        return NugetSymbolPackageContent.objects.none()
    return NugetSymbolPackageContent.objects.filter(pk__in=repo_version.content)


def get_symbol_package_artifact(distribution, package_id_lower, version, filename):
    """The ContentArtifact for a flatcontainer .snupkg request, or None."""
    version = version.lower()
    if filename.lower() != f"{package_id_lower}.{version}.snupkg":
        return None
    package = (
        get_symbol_packages(distribution)
        .filter(package_id_lower=package_id_lower, version_normalized=version)
        .first()
    )
    if package is None:
        return None
    return ContentArtifact.objects.select_related("artifact").filter(content=package).first()


def get_symbol_file(distribution, filename, signature):
    """
    An aiohttp Response with a portable PDB for an SSQP symbol request, or None (404).

    Debuggers ask for symbols/{file}/{signature}/{file}; the PDB is extracted from a
    stored .snupkg whose recorded PDB identities match.
    """
    filename = filename.lower()
    signature = signature.lower()
    candidates = get_symbol_packages(distribution).filter(
        pdb_files__contains=[{"name": filename, "signature": signature}]
    )
    for package in candidates:
        content_artifact = (
            ContentArtifact.objects.select_related("artifact").filter(content=package).first()
        )
        if content_artifact is None or content_artifact.artifact is None:
            continue
        for record in package.pdb_files:
            if record["name"] != filename or record["signature"] != signature:
                continue
            try:
                with content_artifact.artifact.file.open("rb") as fp:
                    body = read_package_file(fp, record["path"])
            except (InvalidNupkgError, OSError):
                body = None
            if body is not None:
                return web.Response(body=body, content_type="application/octet-stream")
    return None


def _package_with_artifact(distribution, package_id_lower, version):
    """The (package, artifact) pair for a stored package, or (package-or-None, None)."""
    package = (
        get_packages(distribution)
        .filter(package_id_lower=package_id_lower, version_normalized=version.lower())
        .first()
    )
    if package is None:
        return None, None
    content_artifact = (
        ContentArtifact.objects.select_related("artifact").filter(content=package).first()
    )
    if content_artifact is None or content_artifact.artifact is None:
        return package, None
    return package, content_artifact.artifact


def get_package_nuspec(distribution, package_id_lower, version, filename):
    """
    An aiohttp Response with the raw .nuspec XML for a flatcontainer request, or None.

    The manifest is extracted from the stored .nupkg, so on-demand packages whose
    artifact was never downloaded yield None (404) until the .nupkg is fetched once.
    """
    if filename.lower() != f"{package_id_lower}.nuspec":
        return None
    _, artifact = _package_with_artifact(distribution, package_id_lower, version)
    if artifact is None:
        return None
    try:
        with artifact.file.open("rb") as fp:
            xml = read_nuspec(fp)
    except (InvalidNupkgError, OSError):
        return None
    return web.Response(body=xml, content_type="application/xml")


# Embedded icons may only be png or jpeg per the nuspec reference.
_ICON_CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def get_package_asset(distribution, package_id_lower, version, asset):
    """
    An aiohttp Response with an embedded asset (icon or readme), or None (404).

    The file is extracted from the stored .nupkg at the path the .nuspec declared, so
    like the .nuspec endpoint this 404s for on-demand packages never yet downloaded,
    and for packages that do not embed the asset.
    """
    package, artifact = _package_with_artifact(distribution, package_id_lower, version)
    if package is None or artifact is None:
        return None
    inner_path = package.icon_file if asset == "icon" else package.readme_file
    if not inner_path:
        return None
    try:
        with artifact.file.open("rb") as fp:
            body = read_package_file(fp, inner_path)
    except (InvalidNupkgError, OSError):
        return None
    if body is None:
        return None
    if asset == "icon":
        extension = "." + inner_path.rsplit(".", 1)[-1].lower() if "." in inner_path else ""
        content_type = _ICON_CONTENT_TYPES.get(extension, "application/octet-stream")
    else:
        content_type = "text/markdown"
    return web.Response(body=body, content_type=content_type)


def _icon_url(package, base):
    """The package's icon URL: our flatcontainer endpoint for embedded icons."""
    if package.icon_file:
        return (
            f"{base}v3-flatcontainer/{package.package_id_lower}/{package.version_normalized}/icon"
        )
    return package.icon_url


def _dependency_range(raw_range):
    """Render a nuspec version (range) attribute as a registration range string."""
    if not raw_range:
        return "(, )"
    if raw_range.startswith(("[", "(")):
        return raw_range
    return f"[{raw_range}, )"


def _catalog_entry(package, base):
    """The catalogEntry object embedded in registration resources."""
    package_url = (
        f"{base}v3-flatcontainer/{package.package_id_lower}/{package.version_normalized}/"
        f"{package.package_id_lower}.{package.version_normalized}.nupkg"
    )
    entry = {
        "@id": f"{base}v3/registrations/{package.package_id_lower}/"
        f"{package.version_normalized}.json",
        "@type": "PackageDetails",
        "authors": package.authors,
        "dependencyGroups": [
            {
                "@type": "PackageDependencyGroup",
                **(
                    {"targetFramework": group["targetFramework"]}
                    if group["targetFramework"]
                    else {}
                ),
                "dependencies": [
                    {
                        "@type": "PackageDependency",
                        "id": dependency["id"],
                        "range": _dependency_range(dependency.get("range")),
                        "registration": f"{base}v3/registrations/"
                        f"{dependency['id'].lower()}/index.json",
                    }
                    for dependency in group["dependencies"]
                ],
            }
            for group in package.dependency_groups
        ],
        "description": package.description,
        "iconUrl": _icon_url(package, base),
        "id": package.package_id,
        "language": "",
        "licenseExpression": package.license_expression,
        "licenseUrl": package.license_url,
        "listed": package.listed,
        "minClientVersion": package.min_client_version,
        "packageContent": package_url,
        "projectUrl": package.project_url,
        "requireLicenseAcceptance": package.require_license_acceptance,
        "summary": package.summary,
        "tags": _split_tags(package.tags),
        "title": package.title,
        "version": package.version_normalized,
    }
    return entry


def _registration_leaf(package, base):
    catalog_entry = _catalog_entry(package, base)
    return {
        "@id": f"{base}v3/registrations/{package.package_id_lower}/"
        f"{package.version_normalized}.json",
        "@type": "Package",
        "catalogEntry": catalog_entry,
        "listed": package.listed,
        "packageContent": catalog_entry["packageContent"],
        "registration": f"{base}v3/registrations/{package.package_id_lower}/index.json",
    }


def _sorted_packages(distribution, package_id_lower):
    return sorted(
        get_packages(distribution).filter(package_id_lower=package_id_lower),
        key=lambda package: version_sort_key(package.version_normalized),
    )


def _page_chunks(packages, page_size):
    """Split a version-sorted package list into registration pages."""
    return [packages[i : i + page_size] for i in range(0, len(packages), page_size)]


def _page_url(base, package_id_lower, chunk):
    return (
        f"{base}v3/registrations/{package_id_lower}/page/"
        f"{chunk[0].version_normalized}/{chunk[-1].version_normalized}.json"
    )


def _full_page(chunk, base, package_id_lower, page_id):
    index_url = f"{base}v3/registrations/{package_id_lower}/index.json"
    return {
        "@id": page_id,
        "@type": "catalog:CatalogPage",
        "count": len(chunk),
        "items": [_registration_leaf(package, base) for package in chunk],
        "lower": chunk[0].version_normalized,
        "parent": index_url,
        "upper": chunk[-1].version_normalized,
    }


def registration_index(distribution, package_id_lower):
    """
    The v3/registrations/{id}/index.json resource, or None if the id is unknown.

    Mirrors nuget.org paging: with up to one page worth of versions the single page is
    inlined; beyond that the index only lists page stubs whose @id must be fetched.
    """
    packages = _sorted_packages(distribution, package_id_lower)
    if not packages:
        return None
    base = base_url(distribution)
    index_url = f"{base}v3/registrations/{package_id_lower}/index.json"
    chunks = _page_chunks(packages, _page_size())
    if len(chunks) == 1:
        page_id = f"{index_url}#page/{packages[0].version_normalized}/"
        page_id += packages[-1].version_normalized
        items = [_full_page(chunks[0], base, package_id_lower, page_id)]
    else:
        items = [
            {
                "@id": _page_url(base, package_id_lower, chunk),
                "@type": "catalog:CatalogPage",
                "count": len(chunk),
                "lower": chunk[0].version_normalized,
                "upper": chunk[-1].version_normalized,
            }
            for chunk in chunks
        ]
    return {
        "@id": index_url,
        "@type": ["catalog:CatalogRoot", "PackageRegistration", "catalog:Permalink"],
        "count": len(items),
        "items": items,
    }


def registration_page(distribution, package_id_lower, lower, upper):
    """The v3/registrations/{id}/page/{lower}/{upper}.json resource, or None."""
    packages = _sorted_packages(distribution, package_id_lower)
    if not packages:
        return None
    base = base_url(distribution)
    for chunk in _page_chunks(packages, _page_size()):
        if (
            chunk[0].version_normalized == lower.lower()
            and chunk[-1].version_normalized == upper.lower()
        ):
            return _full_page(
                chunk, base, package_id_lower, _page_url(base, package_id_lower, chunk)
            )
    return None


def registration_leaf(distribution, package_id_lower, version):
    """The v3/registrations/{id}/{version}.json resource, or None."""
    package = (
        get_packages(distribution)
        .filter(package_id_lower=package_id_lower, version_normalized=version.lower())
        .first()
    )
    if package is None:
        return None
    return _registration_leaf(package, base_url(distribution))


def _split_tags(tags):
    return [tag for tag in re.split(r"[,;\s]+", tags) if tag]


def _package_type_names(package):
    """Declared package type names; no declared types means the implicit Dependency type."""
    names = [entry.get("name", "") for entry in (package.package_types or [])]
    return [name for name in names if name] or ["Dependency"]


def search(
    distribution,
    query="",
    skip=0,
    take=20,
    prerelease=False,
    package_type="",
    sem_ver_level="",
):
    """The SearchQueryService response."""
    base = base_url(distribution)
    include_semver2 = sem_ver_level == "2.0.0"
    by_id = {}
    for package in get_packages(distribution).filter(listed=True).order_by("package_id_lower"):
        if not prerelease and "-" in package.version_normalized:
            continue
        if not include_semver2 and is_semver2(package.version):
            continue
        if package_type and package_type.lower() not in (
            name.lower() for name in _package_type_names(package)
        ):
            continue
        if query:
            haystack = " ".join(
                [package.package_id, package.title, package.tags, package.description]
            ).lower()
            if query.lower() not in haystack:
                continue
        by_id.setdefault(package.package_id_lower, []).append(package)

    data = []
    for package_id_lower, packages in sorted(by_id.items()):
        packages.sort(key=lambda package: version_sort_key(package.version_normalized))
        latest = packages[-1]
        registration_url = f"{base}v3/registrations/{package_id_lower}/index.json"
        data.append(
            {
                "@id": registration_url,
                "@type": "Package",
                "registration": registration_url,
                "id": latest.package_id,
                "version": latest.version_normalized,
                "description": latest.description,
                "summary": latest.summary,
                "title": latest.title,
                "iconUrl": _icon_url(latest, base),
                "licenseUrl": latest.license_url,
                "projectUrl": latest.project_url,
                "tags": _split_tags(latest.tags),
                "authors": [
                    author.strip() for author in latest.authors.split(",") if author.strip()
                ],
                "packageTypes": [{"name": name} for name in _package_type_names(latest)],
                "totalDownloads": 0,
                "verified": False,
                "versions": [
                    {
                        "version": package.version_normalized,
                        "downloads": 0,
                        "@id": f"{base}v3/registrations/{package_id_lower}/"
                        f"{package.version_normalized}.json",
                    }
                    for package in packages
                ],
            }
        )
    total_hits = len(data)
    data = data[skip : skip + take]
    return {"totalHits": total_hits, "data": data}


def handle(distribution, path):
    """
    Serve a NuGet v3 API path relative to the distribution's base path.

    Returns None (let pulpcore keep looking), a ContentArtifact (pulpcore streams it,
    including on-demand fetching), or an aiohttp Response.
    """
    if path == "v3/index.json":
        return web.json_response(service_index(distribution))

    if match := FLATCONTAINER_RE.match(path):
        package_id_lower = match["package_id"].lower()
        if match["version"] is None:
            if (data := flatcontainer_versions(distribution, package_id_lower)) is not None:
                return web.json_response(data)
        elif match["filename"] in ("icon", "readme"):
            return get_package_asset(
                distribution, package_id_lower, match["version"], match["filename"]
            )
        elif match["filename"].lower().endswith(".nuspec"):
            return get_package_nuspec(
                distribution, package_id_lower, match["version"], match["filename"]
            )
        elif match["filename"].lower().endswith(".snupkg"):
            content_artifact = get_symbol_package_artifact(
                distribution, package_id_lower, match["version"], match["filename"]
            )
            if content_artifact is not None:
                return content_artifact
        else:
            content_artifact = get_package_artifact(
                distribution, package_id_lower, match["version"], match["filename"]
            )
            if content_artifact is not None:
                return content_artifact
        return None

    if match := SYMBOLS_RE.match(path):
        if match["filename"].lower() == match["filename2"].lower():
            return get_symbol_file(distribution, match["filename"], match["signature"])
        return None

    if match := REGISTRATION_PAGE_RE.match(path):
        data = registration_page(
            distribution, match["package_id"].lower(), match["lower"], match["upper"]
        )
        if data is not None:
            return web.json_response(data)
        return None

    if match := REGISTRATION_RE.match(path):
        package_id_lower = match["package_id"].lower()
        if match["version"] is None:
            data = registration_index(distribution, package_id_lower)
        else:
            data = registration_leaf(distribution, package_id_lower, match["version"])
        if data is not None:
            return web.json_response(data)
        return None

    return None
