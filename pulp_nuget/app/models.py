"""Models for the pulp_nuget plugin."""

from logging import getLogger

from django.db import models

from pulpcore.plugin.models import Content, Distribution, Remote, Repository
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


class NugetRemote(Remote):
    """
    A Remote for syncing from an upstream NuGet v3 feed.

    The url must point to a v3 service index (e.g. https://api.nuget.org/v3/index.json).
    Only packages listed in ``includes`` are synced.
    """

    TYPE = "nuget"

    # List of package ids to mirror (case-insensitive).
    includes = models.JSONField(default=list)

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"


class NugetRepository(Repository):
    """
    A Repository for NugetPackageContent.
    """

    TYPE = "nuget"

    CONTENT_TYPES = [NugetPackageContent]
    REMOTE_TYPES = [NugetRemote]

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"


class NugetDistribution(Distribution):
    """
    A Distribution that serves a live NuGet v3 API for a repository.

    Content is served directly from the latest (or specified) repository version by a
    custom content handler; no publications are involved.
    """

    TYPE = "nuget"

    class Meta:
        default_related_name = "%(app_label)s_%(model_name)s"
