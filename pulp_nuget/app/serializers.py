"""Serializers for the pulp_nuget plugin."""

from gettext import gettext as _

from rest_framework import serializers

from pulpcore.plugin import models as core_models
from pulpcore.plugin import serializers as platform
from pulpcore.plugin.util import get_domain_pk

from . import models
from .nuspec import InvalidNupkgError, InvalidVersionRangeError, parse_nupkg, parse_package_filter
from .symbols import parse_snupkg


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
    icon_file = serializers.CharField(read_only=True, allow_blank=True)
    readme_file = serializers.CharField(read_only=True, allow_blank=True)
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
                "icon_file",
                "readme_file",
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


class NugetSymbolPackageSerializer(
    platform.SingleArtifactContentUploadSerializer, platform.ContentChecksumSerializer
):
    """
    A Serializer for NugetSymbolPackageContent.

    Symbol packages are created by uploading a .snupkg file; the id and version are
    parsed from the embedded .nuspec, and each portable PDB's SSQP identity is
    extracted so the distribution can serve it to debuggers.
    """

    # The snupkg location is derived from the parsed metadata, not user input.
    relative_path = None

    package_id = serializers.CharField(help_text=_("The NuGet package id."), read_only=True)
    version = serializers.CharField(
        help_text=_("The package version as authored in the .nuspec."), read_only=True
    )
    version_normalized = serializers.CharField(
        help_text=_("The lowercase NuGet-normalized SemVer2 version."), read_only=True
    )
    pdb_files = serializers.JSONField(
        help_text=_(
            "The portable PDBs in the package: archive path, lowercased file name, and "
            "SSQP signature of each."
        ),
        read_only=True,
    )

    def deferred_validate(self, data):
        """Parse the manifest and the PDB identities out of the artifact."""
        data = super().deferred_validate(data)

        artifact = data["artifact"]
        try:
            with artifact.file.open("rb") as fp:
                metadata = parse_snupkg(fp)
        except InvalidNupkgError as exc:
            raise serializers.ValidationError(
                _("The file is not a valid NuGet symbol package: {}").format(exc)
            )

        metadata["package_id_lower"] = metadata["package_id"].lower()
        data.update(metadata)
        return data

    def retrieve(self, validated_data):
        """Return an existing symbol package with the same natural key if there is one."""
        return models.NugetSymbolPackageContent.objects.filter(
            package_id_lower=validated_data["package_id_lower"],
            version_normalized=validated_data["version_normalized"],
            pulp_domain=get_domain_pk(),
        ).first()

    def get_artifacts(self, validated_data):
        """Map the artifact to its flat-container relative path."""
        artifact = validated_data.pop("artifact")
        relative_path = (
            "{package_id_lower}/{version_normalized}/{package_id_lower}.{version_normalized}.snupkg"
        ).format(**validated_data)
        return {relative_path: artifact}

    class Meta:
        model = models.NugetSymbolPackageContent
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
                "pdb_files",
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
        help_text=_(
            "A list of packages to sync. Each entry is a package id (case-insensitive), "
            "optionally followed by a space and a NuGet version range, e.g. "
            "'Serilog' or 'Serilog [2.0,3.0)'. A range only matches prerelease versions "
            "when one of its bounds has a prerelease label (e.g. '[2.0.0-alpha,3.0)')."
        ),
        default=list,
    )
    excludes = serializers.ListField(
        child=serializers.CharField(),
        help_text=_(
            "A list of packages to skip, in the same syntax as includes. Excludes are "
            "applied after includes, e.g. includes=['Serilog'] with "
            "excludes=['Serilog (,2.0)'] syncs only Serilog 2.0 and newer. Unlike "
            "includes, exclude ranges match prerelease versions by pure precedence."
        ),
        default=list,
    )

    def _validate_filter_list(self, value):
        for entry in value:
            try:
                parse_package_filter(entry)
            except InvalidVersionRangeError:
                # The message is built from the entry alone (not the exception) so no
                # exception-derived text reaches the response (CodeQL
                # py/stack-trace-exposure).
                raise serializers.ValidationError(
                    _(
                        "Invalid package filter entry '{}'. An entry is a package id, "
                        "optionally followed by a space and a NuGet version range: "
                        "'Serilog', 'Serilog [2.0,3.0)', 'Serilog (,2.0]', or "
                        "'Serilog 2.0'. Interval bounds must be valid versions in "
                        "ascending order; an exact version needs inclusive brackets "
                        "like '[2.0]'."
                    ).format(entry)
                )
        return value

    def validate_includes(self, value):
        return self._validate_filter_list(value)

    def validate_excludes(self, value):
        return self._validate_filter_list(value)

    class Meta:
        fields = platform.RemoteSerializer.Meta.fields + ("includes", "excludes")
        model = models.NugetRemote


class NugetRepositorySerializer(platform.RepositorySerializer):
    """
    A Serializer for NugetRepository.
    """

    last_sync_details = serializers.JSONField(
        help_text=_("State of the last successful sync, used for sync optimization."),
        read_only=True,
    )
    retain_package_versions = serializers.IntegerField(
        help_text=_(
            "Keep only this many versions of each package id in new repository versions "
            "(newest by NuGet precedence; prereleases rank just below their release). "
            "Applied whenever content is added by sync, push, upload, or modify. "
            "0 (the default) keeps all versions."
        ),
        min_value=0,
        required=False,
    )

    class Meta:
        fields = platform.RepositorySerializer.Meta.fields + (
            "last_sync_details",
            "retain_package_versions",
        )
        model = models.NugetRepository


class NugetRepositorySyncURLSerializer(platform.RepositorySyncURLSerializer):
    """
    A Serializer for syncing a NugetRepository, with an optimization toggle.
    """

    optimize = serializers.BooleanField(
        help_text=_(
            "Skip the sync if the remote and the upstream registrations are unchanged "
            "since the last sync."
        ),
        required=False,
        default=True,
    )


class NugetContentGuardSerializer(platform.ContentGuardSerializer):
    """
    A Serializer for NugetContentGuard.
    """

    class Meta:
        fields = platform.ContentGuardSerializer.Meta.fields
        model = models.NugetContentGuard


class NugetDistributionSerializer(platform.DistributionSerializer):
    """
    A Serializer for NugetDistribution.

    The distribution serves a live NuGet v3 API from its repository; the service index is
    available at ``<base_url>/v3/index.json``.
    """

    class Meta:
        fields = platform.DistributionSerializer.Meta.fields
        model = models.NugetDistribution
