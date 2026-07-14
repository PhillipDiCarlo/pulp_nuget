"""Sync allowlisted packages from an upstream NuGet v3 feed."""

import json
import logging
from gettext import gettext as _

from aiohttp import ClientResponseError

from pulpcore.plugin.models import Artifact, ProgressReport, Remote
from pulpcore.plugin.stages import (
    DeclarativeArtifact,
    DeclarativeContent,
    DeclarativeVersion,
    Stage,
)

from pulp_nuget.app.models import NugetPackageContent, NugetRemote, NugetRepository
from pulp_nuget.app.nuspec import canonical_version

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


def synchronize(remote_pk, repository_pk, mirror):
    """
    Create a new repository version synchronized with the remote's allowlisted packages.

    Args:
        remote_pk (str): The remote PK.
        repository_pk (str): The repository PK.
        mirror (bool): True for mirror mode, False for additive.
    """
    remote = NugetRemote.objects.get(pk=remote_pk)
    repository = NugetRepository.objects.get(pk=repository_pk)

    if not remote.url:
        raise ValueError(_("A remote must have a url specified to synchronize."))
    if not remote.includes:
        raise ValueError(
            _("The remote must specify a non-empty 'includes' package allowlist to synchronize.")
        )

    first_stage = NugetFirstStage(remote)
    DeclarativeVersion(first_stage, repository, mirror=mirror).create()


def _as_string(value, separator=", "):
    """catalogEntry fields like authors/tags can be either a string or a list."""
    if isinstance(value, (list, tuple)):
        return separator.join(str(item) for item in value)
    return value or ""


def _dependency_groups(entry):
    """Normalize catalogEntry dependencyGroups into the model's JSON shape."""
    groups = []
    for group in entry.get("dependencyGroups") or []:
        dependencies = []
        for dependency in group.get("dependencies") or []:
            item = {"id": dependency["id"]}
            if dependency.get("range"):
                item["range"] = dependency["range"]
            dependencies.append(item)
        groups.append(
            {"targetFramework": group.get("targetFramework"), "dependencies": dependencies}
        )
    return groups


class NugetFirstStage(Stage):
    """
    Walk the upstream service index and registration pages for the allowlisted package
    ids, and emit DeclarativeContent for every version found.
    """

    def __init__(self, remote):
        super().__init__()
        self.remote = remote
        self.deferred_download = remote.policy != Remote.IMMEDIATE

    async def _fetch_json(self, url):
        downloader = self.remote.get_downloader(url=url)
        result = await downloader.run()
        with open(result.path, "rb") as fp:
            return json.load(fp)

    def _registrations_base(self, service_index):
        by_type = {}
        for resource in service_index.get("resources", []):
            types = resource.get("@type")
            types = types if isinstance(types, list) else [types]
            for type_ in types:
                by_type.setdefault(type_, resource["@id"])
        for type_ in REGISTRATION_TYPES:
            if type_ in by_type:
                return by_type[type_]
        raise ValueError(
            _("The service index at {} advertises no registrations resource.").format(
                self.remote.url
            )
        )

    async def _package_leaves(self, registration_index):
        for page in registration_index.get("items", []):
            if "items" not in page:
                page = await self._fetch_json(page["@id"])
            for leaf in page.get("items", []):
                yield leaf

    async def run(self):
        service_index = await self._fetch_json(self.remote.url)
        registrations_base = self._registrations_base(service_index).rstrip("/")

        package_ids = sorted({package_id.lower() for package_id in self.remote.includes})
        async with ProgressReport(
            message="Fetching package registrations", code="sync.registrations", total=len(package_ids)
        ) as progress:
            for package_id in package_ids:
                registration_url = f"{registrations_base}/{package_id}/index.json"
                try:
                    registration_index = await self._fetch_json(registration_url)
                except ClientResponseError as exc:
                    if exc.status == 404:
                        log.warning(
                            "Package id '%s' not found in the remote registrations (404), "
                            "skipping.",
                            package_id,
                        )
                        await progress.aincrement()
                        continue
                    raise

                async for leaf in self._package_leaves(registration_index):
                    entry = leaf["catalogEntry"]
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
