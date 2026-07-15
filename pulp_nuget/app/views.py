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

from pulp_nuget.app.models import NugetDistribution


class PackagePublishView(APIView):
    """
    The PackagePublish/2.0.0 resource (``dotnet nuget push``).

    NuGet clients PUT a multipart/form-data body containing one .nupkg to the URL
    advertised in the service index. The package is added to the repository backing
    the distribution; validation (nuspec parsing) happens in the dispatched task,
    mirroring nuget.org's asynchronous 202 semantics.
    """

    parser_classes = [MultiPartParser]
    permission_classes = [IsAuthenticated]

    @extend_schema(exclude=True)
    def put(self, request, base_path):
        """Receive a pushed .nupkg and add it to the distribution's repository."""
        # NuGet clients PUT the advertised URL with a trailing slash appended.
        base_path = base_path.strip("/")
        lookup = {"base_path": base_path}
        if settings.DOMAIN_ENABLED:
            domain_name, _sep, real_base_path = base_path.partition("/")
            lookup = {"pulp_domain__name": domain_name, "base_path": real_base_path}
        distribution = NugetDistribution.objects.filter(**lookup).first()
        if distribution is None:
            raise NotFound(_("No NuGet distribution exists at '{}'.").format(base_path))
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
