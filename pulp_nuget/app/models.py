"""Models for the pulp_nuget plugin."""

from logging import getLogger

from django.conf import settings
from django.db import models

from pulpcore.plugin.models import (
    AutoAddObjPermsMixin,
    Content,
    ContentGuard,
    Distribution,
    Remote,
    Repository,
)
from pulpcore.plugin.util import get_domain_pk

logger = getLogger(__name__)


class NugetPackageContent(Content):
    """
    A NuGet package (.nupkg), the "nuget" content type.

    The natural key is (package_id_lower, version_normalized): the lowercase package id
    and the lowercase NuGet-normalized SemVer2 version, as used in v3 API URLs.
    Metadata is parsed from the .nuspec manifest inside the package.
    """

    TYPE = "package"

    # Natural key (canonical, lowercase).
    package_id_lower = models.CharField(max_length=128)
    version_normalized = models.CharField(max_length=128)

    # Original casing/form, for display and metadata resources.
    package_id = models.CharField(max_length=128)
    version = models.CharField(max_length=128)

    authors = models.TextField(default="", blank=True)
    description = models.TextField(default="", blank=True)
    title = models.TextField(default="", blank=True)
    summary = models.TextField(default="", blank=True)
    tags = models.TextField(default="", blank=True)
    project_url = models.TextField(default="", blank=True)
    icon_url = models.TextField(default="", blank=True)
    license_expression = models.TextField(default="", blank=True)
    license_file = models.TextField(default="", blank=True)
    license_url = models.TextField(default="", blank=True)
    require_license_acceptance = models.BooleanField(default=False)
    min_client_version = models.CharField(max_length=64, default="", blank=True)
    # List of dependency groups: [{"targetFramework": str|None, "dependencies": [...]}]
    dependency_groups = models.JSONField(default=list, blank=True)
    # List of declared package types: [{"name": str, "version": str?}]; empty means the
    # implicit "Dependency" type.
    package_types = models.JSONField(default=list, blank=True)
    # Unlisted packages stay downloadable by exact version but are hidden from search
    # and marked listed=false in registrations. Mutable; global per content unit.
    listed = models.BooleanField(default=True)

    _pulp_domain = models.ForeignKey("core.Domain", default=get_domain_pk, on_delete=models.PROTECT)

    @property
    def relative_path(self):
        """The flat-container relative path of the .nupkg within a repository."""
        return (
            f"{self.package_id_lower}/{self.version_normalized}/"
            f"{self.package_id_lower}.{self.version_normalized}.nupkg"
        )

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"
        unique_together = ("package_id_lower", "version_normalized", "_pulp_domain")


class NugetRemote(Remote, AutoAddObjPermsMixin):
    """
    A Remote for syncing from an upstream NuGet v3 feed.

    The url must point to a v3 service index (e.g. https://api.nuget.org/v3/index.json).
    Only packages listed in ``includes`` are synced; ``excludes`` filters them further.
    Entries are package ids, optionally followed by a NuGet version range, e.g.
    ``"Serilog"`` or ``"Serilog [2.0,3.0)"``.
    """

    TYPE = "nuget"

    # Package ids (case-insensitive) to mirror, each optionally "<id> <version-range>".
    includes = models.JSONField(default=list)
    # Same syntax; matching packages are skipped even when includes matches them.
    excludes = models.JSONField(default=list)

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"
        permissions = [
            ("manage_roles_nugetremote", "Can manage roles on nuget remotes"),
        ]


class NugetRepository(Repository, AutoAddObjPermsMixin):
    """
    A Repository for NugetPackageContent.
    """

    TYPE = "nuget"

    CONTENT_TYPES = [NugetPackageContent]
    REMOTE_TYPES = [NugetRemote]

    # State of the last sync, used to skip syncs when nothing changed (like pulp_file).
    last_sync_details = models.JSONField(default=dict)

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"
        permissions = [
            ("sync_nugetrepository", "Can start a sync task"),
            ("modify_nugetrepository", "Can modify content of the repository"),
            ("manage_roles_nugetrepository", "Can manage roles on nuget repositories"),
            ("repair_nugetrepository", "Can repair repository versions"),
        ]


class NugetContentGuard(ContentGuard, AutoAddObjPermsMixin):
    """
    A content guard for private NuGet feeds.

    Works like pulpcore's RBAC content guard (download permission at the model, domain,
    or object level), but challenges unauthenticated requests with a 401 and
    ``WWW-Authenticate: Basic`` instead of a plain 403. NuGet clients (dotnet, nuget.exe,
    MSBuild) only send the credentials configured in nuget.config after such a
    challenge, so the stock RBAC guard cannot protect a feed they can restore from.
    """

    TYPE = "nuget"

    def permit(self, request):
        """Permit users with the download permission; challenge anonymous clients."""
        drf_request = request.get("drf_request", None)
        user = getattr(drf_request, "user", None)
        if user is None or not user.is_authenticated:
            # Not PermissionError: pulpcore would turn that into a 403, and NuGet
            # clients only retry with credentials after a 401 Basic challenge.
            from aiohttp.web_exceptions import HTTPUnauthorized

            raise HTTPUnauthorized(
                headers={"WWW-Authenticate": 'Basic realm="pulp_nuget", charset="UTF-8"'}
            )
        permission = "nuget.download_nugetcontentguard"
        if user.has_perm(permission) or user.has_perm(permission, obj=self):
            return
        if settings.DOMAIN_ENABLED and user.has_perm(permission, obj=self.pulp_domain):
            return
        raise PermissionError("User is not authorized to download from this feed.")

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"
        permissions = [
            ("download_nugetcontentguard", "Can download content protected by this guard"),
            ("manage_roles_nugetcontentguard", "Can manage roles on nuget content guards"),
        ]


class NugetDistribution(Distribution, AutoAddObjPermsMixin):
    """
    A Distribution that serves a live NuGet v3 API for a repository.

    Content is served directly from the latest (or specified) repository version by a
    custom content handler; no publications are involved.
    """

    TYPE = "nuget"

    def content_handler(self, path):
        """Serve the NuGet v3 API (service index, flatcontainer, registrations)."""
        from pulp_nuget.app import v3_api

        return v3_api.handle(self, path)

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"
        permissions = [
            (
                "publish_nugetdistribution",
                "Can push, unlist, and relist packages via the distribution's publish endpoint",
            ),
            ("manage_roles_nugetdistribution", "Can manage roles on nuget distributions"),
        ]
