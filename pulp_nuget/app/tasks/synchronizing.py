"""Sync allowlisted packages from an upstream NuGet v3 feed."""

import json
import logging
from gettext import gettext as _
from hashlib import sha256

from aiohttp import ClientResponseError

from pulpcore.plugin.exceptions import SyncError
from pulpcore.plugin.models import Artifact, ProgressReport, Remote
from pulpcore.plugin.stages import (
    DeclarativeArtifact,
    DeclarativeContent,
    DeclarativeVersion,
    Stage,
)

from pulp_nuget.app.models import NugetPackageContent, NugetRemote, NugetRepository
from pulp_nuget.app.nuspec import (
    InvalidVersionRangeError,
    canonical_version,
    parse_package_filter,
)

log = logging.getLogger(__name__)

# Preferred registration resources, most capable (SemVer2, gzipped) first.
REGISTRATION_TYPES = (
    "RegistrationsBaseUrl/3.6.0",
    "RegistrationsBaseUrl/3.4.0",
    "RegistrationsBaseUrl/3.0.0-rc",
    "RegistrationsBaseUrl/3.0.0-beta",
    "RegistrationsBaseUrl/Versioned",
    "RegistrationsBaseUrl",
)


def _parse_filters(entries):
    """Parse includes/excludes entries into {package_id_lower: [VersionRange or None]}."""
    filters = {}
    for entry in entries:
        try:
            package_id, version_range = parse_package_filter(entry)
        except InvalidVersionRangeError as exc:
            raise SyncError(str(exc))
        filters.setdefault(package_id, []).append(version_range)
    return filters


def _registrations_base(service_index, remote_url):
    """The registrations base URL advertised by a service index."""
    by_type = {}
    for resource in service_index.get("resources", []):
        types = resource.get("@type")
        types = types if isinstance(types, list) else [types]
        for type_ in types:
            by_type.setdefault(type_, resource["@id"])
    for type_ in REGISTRATION_TYPES:
        if type_ in by_type:
            return by_type[type_].rstrip("/")
    raise SyncError(
        _("The service index at {} advertises no registrations resource.").format(remote_url)
    )


def _should_optimize_sync(sync_details, last_sync_details, version):
    """Whether the sync can be skipped because nothing changed since the previous one."""
    if not last_sync_details:
        return False
    # Switching to immediate download may need to fetch artifacts even without changes.
    if (
        last_sync_details.get("download_policy") != "immediate"
        and sync_details["download_policy"] == "immediate"
    ):
        return False
    for key in (
        "remote_pk",
        "url",
        "mirror",
        "includes",
        "excludes",
        "most_recent_version",
        "registration_checksums",
    ):
        if last_sync_details.get(key) != sync_details[key]:
            return False
    # With immediate policy, artifacts may be missing after a storage reclaim.
    if sync_details["download_policy"] == "immediate":
        from pulpcore.plugin.models import ContentArtifact

        if ContentArtifact.objects.filter(
            content__in=version.content, artifact__isnull=True
        ).exists():
            return False
    return True


def synchronize(remote_pk, repository_pk, mirror, optimize=True):
    """
    Create a new repository version synchronized with the remote's allowlisted packages.

    Args:
        remote_pk (str): The remote PK.
        repository_pk (str): The repository PK.
        mirror (bool): True for mirror mode, False for additive.
        optimize (bool): Skip the sync when the remote and the upstream registration
            indexes are unchanged since the last sync.
    """
    remote = NugetRemote.objects.get(pk=remote_pk)
    repository = NugetRepository.objects.get(pk=repository_pk)

    if not remote.url:
        raise SyncError(_("A remote must have a url specified to synchronize."))
    if not remote.includes:
        raise SyncError(
            _("The remote must specify a non-empty 'includes' package allowlist to synchronize.")
        )

    includes = _parse_filters(remote.includes)
    excludes = _parse_filters(remote.excludes)
    # An exclude entry without a version range drops the package id entirely.
    package_ids = sorted(
        package_id
        for package_id in includes
        if not any(version_range is None for version_range in excludes.get(package_id, []))
    )
    if not package_ids:
        raise SyncError(_("Every package in 'includes' is matched by 'excludes'."))

    # Fetch the service index and every registration index up front: their checksums
    # decide whether the sync can be skipped, and the first stage reuses the documents.
    service_index_result = remote.get_downloader(url=remote.url).fetch()
    with open(service_index_result.path, "rb") as fp:
        service_index = json.load(fp)
    registrations_base = _registrations_base(service_index, remote.url)

    registration_indexes = {}
    registration_checksums = {}
    for package_id in package_ids:
        registration_url = f"{registrations_base}/{package_id}/index.json"
        try:
            result = remote.get_downloader(url=registration_url).fetch()
        except ClientResponseError as exc:
            if exc.status == 404:
                log.warning(
                    "Package id '%s' not found in the remote registrations (404), skipping.",
                    package_id,
                )
                registration_indexes[package_id] = None
                registration_checksums[package_id] = None
                continue
            raise
        with open(result.path, "rb") as fp:
            data = fp.read()
        registration_indexes[package_id] = json.loads(data)
        registration_checksums[package_id] = sha256(data).hexdigest()

    version = repository.latest_version()
    sync_details = {
        "remote_pk": str(remote.pk),
        "url": remote.url,
        "download_policy": remote.policy,
        "mirror": mirror,
        "includes": sorted(remote.includes),
        "excludes": sorted(remote.excludes),
        "most_recent_version": version.number,
        "registration_checksums": registration_checksums,
    }

    if optimize and _should_optimize_sync(sync_details, repository.last_sync_details, version):
        with ProgressReport(
            message="Skipping sync (no change from previous sync)",
            code="sync.was_skipped",
        ) as progress:
            progress.total = 1
            progress.done = 1
        return

    first_stage = NugetFirstStage(remote, registration_indexes, includes, excludes)
    repository_version = DeclarativeVersion(first_stage, repository, mirror=mirror).create()

    if repository_version:
        sync_details["most_recent_version"] = repository_version.number
    repository.last_sync_details = sync_details
    repository.save()


def _as_string(value, separator=", "):
    """catalogEntry fields like authors/tags may be a string or a list of strings."""
    if isinstance(value, list):
        return separator.join(str(item) for item in value if item)
    return value or ""


def _dependency_groups(entry):
    """
    Convert a catalogEntry's dependencyGroups to the model's nuspec-shaped structure.

    Registration dependency entries use "id"/"range"; the model stores what parse_nuspec
    produces from a manifest: {"targetFramework", "dependencies": [{"id", "version", ...}]}.
    """
    groups = []
    for group in entry.get("dependencyGroups", []):
        dependencies = []
        for dependency in group.get("dependencies", []):
            dependencies.append(
                {
                    "id": dependency.get("id", ""),
                    "version": dependency.get("range") or "",
                    "include": dependency.get("include") or "",
                    "exclude": dependency.get("exclude") or "",
                }
            )
        groups.append(
            {
                "targetFramework": group.get("targetFramework") or "",
                "dependencies": dependencies,
            }
        )
    return groups


class NugetFirstStage(Stage):
    """
    The first stage of the sync pipeline: declare filtered content from registrations.

    Registration indexes are pre-fetched by the sync task; this stage walks their pages
    (fetching external pages only when their version window can match the include
    filters) and emits DeclarativeContent for every wanted package version.
    """

    def __init__(self, remote, registration_indexes, includes, excludes):
        super().__init__()
        self.remote = remote
        self.registration_indexes = registration_indexes
        self.includes = includes
        self.excludes = excludes
        self.deferred_download = remote.policy != Remote.IMMEDIATE

    async def _fetch_json(self, url):
        downloader = self.remote.get_downloader(url=url)
        result = await downloader.run()
        with open(result.path, "rb") as fp:
            return json.load(fp)

    def _wanted(self, package_id, version):
        """
        Whether a version passes the include ranges and is not excluded.

        Include ranges select conservatively (prereleases only when a bound is
        prerelease); exclude ranges remove aggressively (pure precedence, so
        ``(,2.0)`` also drops 2.0's prereleases).
        """
        include_ranges = self.includes.get(package_id, [])
        if not any(
            version_range is None or version_range.matches_for_include(version)
            for version_range in include_ranges
        ):
            return False
        return not any(
            version_range is not None and version_range.contains(version)
            for version_range in self.excludes.get(package_id, [])
        )

    def _page_may_match(self, package_id, page):
        """
        Whether a registration page's [lower, upper] window can contain wanted versions.

        Lets the stage skip downloading external pages that the include ranges rule out
        entirely (e.g. one old version out of a 600-version package).
        """
        lower, upper = page.get("lower"), page.get("upper")
        if not lower or not upper:
            return True
        include_ranges = self.includes.get(package_id, [])
        if any(version_range is None for version_range in include_ranges):
            return True
        return any(
            not version_range.excludes_all_below(upper)
            and not version_range.excludes_all_above(lower)
            for version_range in include_ranges
        )

    async def _package_leaves(self, package_id, registration_index):
        for page in registration_index.get("items", []):
            if "items" not in page:
                if not self._page_may_match(package_id, page):
                    continue
                page = await self._fetch_json(page["@id"])
            for leaf in page.get("items", []):
                yield leaf

    async def run(self):
        async with ProgressReport(
            message="Fetching package registrations",
            code="sync.registrations",
            total=len(self.registration_indexes),
        ) as progress:
            for package_id, registration_index in sorted(self.registration_indexes.items()):
                if registration_index is None:
                    await progress.aincrement()
                    continue
                async for leaf in self._package_leaves(package_id, registration_index):
                    entry = leaf["catalogEntry"]
                    if not self._wanted(package_id, entry["version"]):
                        continue
                    package = NugetPackageContent(
                        package_id=entry["id"],
                        package_id_lower=entry["id"].lower(),
                        version=entry["version"],
                        version_normalized=canonical_version(entry["version"]),
                        authors=_as_string(entry.get("authors")),
                        description=entry.get("description") or "",
                        title=entry.get("title") or "",
                        summary=entry.get("summary") or "",
                        tags=_as_string(entry.get("tags"), separator=" "),
                        project_url=entry.get("projectUrl") or "",
                        icon_url=entry.get("iconUrl") or "",
                        license_expression=entry.get("licenseExpression") or "",
                        license_url=entry.get("licenseUrl") or "",
                        require_license_acceptance=bool(entry.get("requireLicenseAcceptance")),
                        min_client_version=entry.get("minClientVersion") or "",
                        dependency_groups=_dependency_groups(entry),
                        # catalogEntry has no packageTypes, so synced content keeps the
                        # default [] (implicit Dependency). Missing "listed" means listed.
                        listed=entry.get("listed") is not False,
                    )
                    url = leaf.get("packageContent") or entry.get("packageContent")
                    if not url:
                        log.warning(
                            "No packageContent URL for %s %s, skipping.",
                            entry["id"],
                            entry["version"],
                        )
                        continue
                    declarative_artifact = DeclarativeArtifact(
                        artifact=Artifact(),
                        url=url,
                        relative_path=package.relative_path,
                        remote=self.remote,
                        deferred_download=self.deferred_download,
                    )
                    await self.put(
                        DeclarativeContent(content=package, d_artifacts=[declarative_artifact])
                    )
                await progress.aincrement()
