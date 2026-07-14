"""Viewsets for the pulp_nuget plugin."""

from django_filters import CharFilter
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action

from pulpcore.plugin import viewsets as core
from pulpcore.plugin.actions import ModifyRepositoryActionMixin
from pulpcore.plugin.serializers import (
    AsyncOperationResponseSerializer,
    RepositorySyncURLSerializer,
)
from pulpcore.plugin.tasking import dispatch

from . import models, serializers, tasks


class NugetPackageFilter(core.ContentFilter):
    """
    FilterSet for NugetPackageContent.
    """

    package_id = CharFilter(field_name="package_id_lower", lookup_expr="iexact")
    version = CharFilter(field_name="version_normalized", lookup_expr="iexact")

    class Meta:
        model = models.NugetPackageContent
        fields = ["package_id", "version"]


class NugetPackageViewSet(core.SingleArtifactContentUploadViewSet):
    """
    A ViewSet for NugetPackageContent.

    Packages are created by uploading a .nupkg file; all metadata is parsed from the
    embedded .nuspec manifest.
    """

    endpoint_name = "packages"
    queryset = models.NugetPackageContent.objects.prefetch_related("_artifacts")
    serializer_class = serializers.NugetPackageSerializer
    filterset_class = NugetPackageFilter


class NugetRemoteViewSet(core.RemoteViewSet):
    """
    A ViewSet for NugetRemote.
    """

    endpoint_name = "nuget"
    queryset = models.NugetRemote.objects.all()
    serializer_class = serializers.NugetRemoteSerializer


class NugetRepositoryViewSet(core.RepositoryViewSet, ModifyRepositoryActionMixin):
    """
    A ViewSet for NugetRepository.
    """

    endpoint_name = "nuget"
    queryset = models.NugetRepository.objects.all()
    serializer_class = serializers.NugetRepositorySerializer

    @extend_schema(
        description="Trigger an asynchronous task to sync content from a NuGet v3 feed.",
        summary="Sync from remote",
        responses={202: AsyncOperationResponseSerializer},
    )
    @action(detail=True, methods=["post"], serializer_class=RepositorySyncURLSerializer)
    def sync(self, request, pk):
        """
        Dispatches a sync task.
        """
        repository = self.get_object()
        serializer = RepositorySyncURLSerializer(
            data=request.data, context={"request": request, "repository_pk": pk}
        )
        serializer.is_valid(raise_exception=True)
        remote = serializer.validated_data.get("remote", repository.remote)
        mirror = serializer.validated_data.get("mirror", False)

        result = dispatch(
            tasks.synchronize,
            shared_resources=[remote],
            exclusive_resources=[repository],
            kwargs={
                "remote_pk": str(remote.pk),
                "repository_pk": str(repository.pk),
                "mirror": mirror,
            },
        )
        return core.OperationPostponedResponse(result, request)


class NugetRepositoryVersionViewSet(core.RepositoryVersionViewSet):
    """
    A ViewSet for NugetRepositoryVersion.
    """

    parent_viewset = NugetRepositoryViewSet


class NugetDistributionViewSet(core.DistributionViewSet):
    """
    A ViewSet for NugetDistribution.

    The distribution serves a live NuGet v3 API; point clients at
    ``<base_url>/v3/index.json``.
    """

    endpoint_name = "nuget"
    queryset = models.NugetDistribution.objects.all()
    serializer_class = serializers.NugetDistributionSerializer
