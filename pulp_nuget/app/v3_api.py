"""
Builders for the NuGet v3 API resources served by a NugetDistribution.

The JSON shapes mirror the resources served by api.nuget.org; when a client fails to
restore, diff our response against the equivalent api.nuget.org resource.

Endpoints (relative to a distribution's base URL):
- v3/index.json                                       service index
- v3-flatcontainer/{id}/index.json                    package versions
- v3-flatcontainer/{id}/{version}/{id}.{version}.nupkg
- v3/registrations/{id}/index.json                    registration index (inlined page)
- v3/registrations/{id}/{version}.json                registration leaf
- v3/search                                           SearchQueryService (query params, so it
                                                      is served by a content-app route, see
                                                      content.py)
"""

import re

from aiohttp import web
from django.conf import settings

from pulpcore.plugin.models import ContentArtifact

from pulp_nuget.app.nuspec import version_sort_key

FLATCONTAINER_RE = re.compile(
    r"^v3-flatcontainer/(?P<package_id>[^/]+)/(?:index\.json$|(?P<version>[^/]+)/"
    r"(?P<filename>[^/]+\.nupkg)$)"
)
REGISTRATION_RE = re.compile(
    r"^v3/registrations/(?P<package_id>[^/]+)/(?:index\.json$|(?P<version>[^/]+)\.json$)"
)


def base_url(distribution):
    """The absolute base URL of this distribution, with a trailing slash."""
    origin = settings.CONTENT_ORIGIN.strip("/")
    prefix = settings.CONTENT_PATH_PREFIX.strip("/")
    parts = [origin, prefix]
    if settings.DOMAIN_ENABLED:
        parts.append(distribution.pulp_domain.name)
    parts.append(distribution.base_path.strip("/"))
    return "/".join(parts) + "/"


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
        "iconUrl": package.icon_url,
        "id": package.package_id,
        "language": "",
        "licenseExpression": package.license_expression,
        "licenseUrl": package.license_url,
        "listed": True,
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
    return {
        "@id": f"{base}v3/registrations/{package.package_id_lower}/"
        f"{package.version_normalized}.json",
        "@type": "Package",
        "catalogEntry": _catalog_entry(package, base),
        "listed": True,
        "packageContent": _catalog_entry(package, base)["packageContent"],
        "registration": f"{base}v3/registrations/{package.package_id_lower}/index.json",
    }


def registration_index(distribution, package_id_lower):
    """The v3/registrations/{id}/index.json resource, or None if the id is unknown."""
    packages = sorted(
        get_packages(distribution).filter(package_id_lower=package_id_lower),
        key=lambda package: version_sort_key(package.version_normalized),
    )
    if not packages:
        return None
    base = base_url(distribution)
    index_url = f"{base}v3/registrations/{package_id_lower}/index.json"
    page = {
        "@id": f"{index_url}#page/{packages[0].version_normalized}/"
        f"{packages[-1].version_normalized}",
        "@type": "catalog:CatalogPage",
        "count": len(packages),
        "lower": packages[0].version_normalized,
        "upper": packages[-1].version_normalized,
        "parent": index_url,
        "items": [_registration_leaf(package, base) for package in packages],
    }
    return {
        "@id": index_url,
        "@type": ["catalog:CatalogRoot", "PackageRegistration", "catalog:Permalink"],
        "count": 1,
        "items": [page],
    }


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


def search(distribution, query="", skip=0, take=20, prerelease=False):
    """The SearchQueryService response."""
    base = base_url(distribution)
    by_id = {}
    for package in get_packages(distribution).order_by("package_id_lower"):
        if not prerelease and "-" in package.version_normalized:
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
                "iconUrl": latest.icon_url,
                "licenseUrl": latest.license_url,
                "projectUrl": latest.project_url,
                "tags": _split_tags(latest.tags),
                "authors": [author.strip() for author in latest.authors.split(",") if author],
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
        else:
            content_artifact = get_package_artifact(
                distribution, package_id_lower, match["version"], match["filename"]
            )
            if content_artifact is not None:
                return content_artifact
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
