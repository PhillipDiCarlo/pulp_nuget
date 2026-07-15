"""Extra API views for pulp_nuget (the NuGet push protocol)."""

from gettext import gettext as _

from django.conf import settings
from django.db import DatabaseError, IntegrityError
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from pulpcore.plugin.models import Artifact
from pulpcore.plugin.tasking import dispatch, general_create
from pulpcore.plugin.util import get_domain, get_url

from pulp_nuget.app import v3_api
from pulp_nuget.app.models import NugetDistribution
from pulp_nuget.app.nuspec import InvalidNuspecError, canonical_version


def _get_distribution(base_path):
    """Resolve a NugetDistribution from a (domain-prefixed) base path, or raise NotFound."""
    lookup = {"base_path": base_path}
    if settings.DOMAIN_ENABLED:
        domain_name, _sep, real_base_path = base_path.partition("/")
        lookup = {"pulp_domain__name": domain_name, "base_path": real_base_path}
    distribution = NugetDistribution.objects.filter(**lookup).first()
    if distribution is None:
        raise NotFound(_("No NuGet distribution exists at '{}'.").format(base_path))
    return distribution


class PackagePublishView(APIView):
    """
    The PackagePublish/2.0.0 resource.

    - PUT <base_path>: ``dotnet nuget push``. NuGet clients PUT a multipart/form-data
      body containing one .nupkg to the URL advertised in the service index. The package
      is added to the repository backing the distribution; validation (nuspec parsing)
      happens in the dispatched task, mirroring nuget.org's asynchronous 202 semantics.
    - DELETE <base_path>/{id}/{version}: ``dotnet nuget delete``. Unlists the package
      (nuget.org semantics): it stays downloadable by exact version but is hidden from
      search and marked listed=false in registrations.
    - POST <base_path>/{id}/{version}: relist a previously unlisted package.

    Authentication is HTTP basic; the X-NuGet-ApiKey header is deliberately ignored
    (clients require --api-key, any value works — credentials belong in nuget.config).
    """

    parser_classes = [MultiPartParser]
    permission_classes = [IsAuthenticated]

    @extend_schema(exclude=True)
    def put(self, request, base_path):
        """Receive a pushed .nupkg and add it to the distribution's repository."""
        # NuGet clients PUT the advertised URL with a trailing slash appended.
        base_path = base_path.strip("/")
        distribution = _get_distribution(base_path)
        if distribution.repository is None:
            raise ValidationError(
                _(
                    "The distribution at '{}' has no repository; packages cannot be pushed to it."
                ).format(base_path)
            )
        repository = distribution.repository.cast()

        files = list(request.FILES.values())
        if len(files) != 1:
            raise ValidationError(_("Exactly one package file must be provided."))

        artifact = Artifact.init_and_validate(files[0])
        try:
            existing = Artifact.objects.get(sha256=artifact.sha256, pulp_domain=get_domain())
            existing.touch()
            artifact = existing
        except (Artifact.DoesNotExist, DatabaseError):
            try:
                artifact.save()
            except IntegrityError:
                artifact = Artifact.objects.get(sha256=artifact.sha256, pulp_domain=get_domain())

        task = dispatch(
            general_create,
            exclusive_resources=[repository],
            args=("nuget", "NugetPackageSerializer"),
            kwargs={
                "data": {"artifact": get_url(artifact), "repository": get_url(repository)},
                "context": {},
            },
        )
        # NuGet clients only need the 202; the task href is for API consumers and tests.
        return Response({"task": get_url(task)}, status=status.HTTP_202_ACCEPTED)

    def _find_package(self, base_path):
        """Resolve <base_path>/{id}/{version} to a package served by the distribution."""
        parts = base_path.strip("/").rsplit("/", 2)
        if len(parts) != 3:
            raise NotFound(
                _("Expected a '<base_path>/{{id}}/{{version}}' path, got '{}'.").format(base_path)
            )
        base_path, package_id, version = parts
        distribution = _get_distribution(base_path)
        try:
            version_normalized = canonical_version(version)
        except InvalidNuspecError:
            raise NotFound(_("Invalid package version '{}'.").format(version))
        package = (
            v3_api.get_packages(distribution)
            .filter(package_id_lower=package_id.lower(), version_normalized=version_normalized)
            .first()
        )
        if package is None:
            raise NotFound(
                _("The distribution at '{}' does not serve {} {}.").format(
                    base_path, package_id, version
                )
            )
        return package

    @extend_schema(exclude=True)
    def delete(self, request, base_path):
        """Unlist a package version (``dotnet nuget delete``)."""
        package = self._find_package(base_path)
        if package.listed:
            package.listed = False
            package.save(update_fields=["listed"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(exclude=True)
    def post(self, request, base_path):
        """Relist a previously unlisted package version."""
        package = self._find_package(base_path)
        if not package.listed:
            package.listed = True
            package.save(update_fields=["listed"])
        return Response(status=status.HTTP_200_OK)
