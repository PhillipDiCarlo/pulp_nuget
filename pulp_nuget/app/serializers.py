"""Serializers for the pulp_nuget plugin."""

from gettext import gettext as _

from rest_framework import serializers

from pulpcore.plugin import models as core_models
from pulpcore.plugin import serializers as platform
from pulpcore.plugin.util import get_domain_pk

from . import models
from .nuspec import InvalidNupkgError, parse_nupkg


class NugetPackageSerializer(
    platform.SingleArtifactContentUploadSerializer, platform.ContentChecksumSerializer
):
    """
    A Serializer for NugetPackageContent.

    All metadata is parsed server-side from the .nuspec inside the uploaded .nupkg;
    the only inputs are the file (or artifact/upload/file_url) and optionally a repository.
    """

    # The nupkg location is derived from the parsed metadata, not user input.
    relative_path = None

    package_id = serializers.CharField(help_text=_("The NuGet package id."), read_only=True)
    version = serializers.CharField(
        help_text=_("The package version as authored in the .nuspec."), read_only=True
    )
    version_normalized = serializers.CharField(
        help_text=_("The lowercase NuGet-normalized SemVer2 version."), read_only=True
    )
    authors = serializers.CharField(read_only=True, allow_blank=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    title = serializers.CharField(read_only=True, allow_blank=True)
    summary = serializers.CharField(read_only=True, allow_blank=True)
    tags = serializers.CharField(read_only=True, allow_blank=True)
    project_url = serializers.CharField(read_only=True, allow_blank=True)
    icon_url = serializers.CharField(read_only=True, allow_blank=True)
    license_expression = serializers.CharField(read_only=True, allow_blank=True)
    license_file = serializers.CharField(read_only=True, allow_blank=True)
    license_url = serializers.CharField(read_only=True, allow_blank=True)
    require_license_acceptance = serializers.BooleanField(read_only=True)
    min_client_version = serializers.CharField(read_only=True, allow_blank=True)
    dependency_groups = serializers.JSONField(read_only=True)
    package_types = serializers.JSONField(read_only=True)
    listed = serializers.BooleanField(
        help_text=_(
            "Whether the package is listed. Unlisted packages are hidden from search but "
            "remain downloadable by exact version."
        ),
        read_only=True,
    )

    def deferred_validate(self, data):
        """Parse the .nuspec metadata out of the artifact."""
        data = super().deferred_validate(data)

        artifact = data["artifact"]
        try:
            with artifact.file.open("rb") as fp:
                metadata = parse_nupkg(fp)
        except InvalidNupkgError as exc:
            raise serializers.ValidationError(
                _("The file is not a valid NuGet package: {}").format(exc)
            )

        metadata["package_id_lower"] = metadata["package_id"].lower()
        data.update(metadata)
        return data

    def retrieve(self, validated_data):
        """Return an existing package with the same natural key if there is one."""
        return models.NugetPackageContent.objects.filter(
            package_id_lower=validated_data["package_id_lower"],
            version_normalized=validated_data["version_normalized"],
            pulp_domain=get_domain_pk(),
        ).first()

    def get_artifacts(self, validated_data):
        """Map the artifact to its flat-container relative path."""
        artifact = validated_data.pop("artifact")
        relative_path = (
            "{package_id_lower}/{version_normalized}/{package_id_lower}.{version_normalized}.nupkg"
        ).format(**validated_data)
        return {relative_path: artifact}

    class Meta:
        model = models.NugetPackageContent
        fields = (
            tuple(
                f
                for f in platform.SingleArtifactContentUploadSerializer.Meta.fields
                if f != "relative_path"
            )
            + platform.ContentChecksumSerializer.Meta.fields
            + (
                "package_id",
                "version",
                "version_normalized",
                "authors",
                "description",
                "title",
                "summary",
                "tags",
                "project_url",
                "icon_url",
                "license_expression",
                "license_file",
                "license_url",
                "require_license_acceptance",
                "min_client_version",
                "dependency_groups",
                "package_types",
                "listed",
            )
        )


class NugetRemoteSerializer(platform.RemoteSerializer):
    """
    A Serializer for NugetRemote.
    """

    url = serializers.CharField(
        help_text=_(
            "The URL of a NuGet v3 service index, e.g. https://api.nuget.org/v3/index.json"
        ),
    )
    policy = serializers.ChoiceField(
        help_text=_(
            "The policy to use when downloading content. The possible values include: "
            "'immediate' and 'on_demand'. 'immediate' is the default."
        ),
        choices=[
            (core_models.Remote.IMMEDIATE, "When syncing, download all metadata and content now."),
            (
                core_models.Remote.ON_DEMAND,
                "When syncing, download metadata, but do not download content now. Instead, "
                "download content as clients request it, and save it in Pulp to be served for "
                "future client requests.",
            ),
        ],
        default=core_models.Remote.IMMEDIATE,
    )
    includes = serializers.ListField(
        child=serializers.CharField(),
        help_text=_("A list of package ids to sync (case-insensitive)."),
        default=list,
    )

    class Meta:
        fields = platform.RemoteSerializer.Meta.fields + ("includes",)
        model = models.NugetRemote


class NugetRepositorySerializer(platform.RepositorySerializer):
    """
    A Serializer for NugetRepository.
    """

    class Meta:
        fields = platform.RepositorySerializer.Meta.fields
        model = models.NugetRepository


class NugetDistributionSerializer(platform.DistributionSerializer):
    """
    A Serializer for NugetDistribution.

    The distribution serves a live NuGet v3 API from its repository; the service index is
    available at ``<base_url>/v3/index.json``.
    """

    class Meta:
        fields = platform.DistributionSerializer.Meta.fields
        model = models.NugetDistribution
