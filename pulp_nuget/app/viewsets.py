"""Viewsets for the pulp_nuget plugin."""

from django_filters import CharFilter
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action

from pulpcore.plugin import viewsets as core
from pulpcore.plugin.actions import ModifyRepositoryActionMixin
from pulpcore.plugin.serializers import AsyncOperationResponseSerializer
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

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "retrieve"],
                "principal": "authenticated",
                "effect": "allow",
            },
            {
                "action": ["create"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_required_repo_perms_on_upload:nuget.modify_nugetrepository",
                    "has_required_repo_perms_on_upload:nuget.view_nugetrepository",
                    "has_upload_param_model_or_domain_or_obj_perms:core.change_upload",
                ],
            },
            {
                "action": ["set_label", "unset_label"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_perms:core.manage_content_labels",
                ],
            },
        ],
        "queryset_scoping": {"function": "scope_queryset"},
    }


class NugetRemoteViewSet(core.RemoteViewSet, core.RolesMixin):
    """
    A ViewSet for NugetRemote.
    """

    endpoint_name = "nuget"
    queryset = models.NugetRemote.objects.all()
    serializer_class = serializers.NugetRemoteSerializer
    queryset_filtering_required_permission = "nuget.view_nugetremote"

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "my_permissions"],
                "principal": "authenticated",
                "effect": "allow",
            },
            {
                "action": ["create"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_perms:nuget.add_nugetremote",
            },
            {
                "action": ["retrieve"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:nuget.view_nugetremote",
            },
            {
                "action": ["update", "partial_update", "set_label", "unset_label"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.change_nugetremote",
                    "has_model_or_domain_or_obj_perms:nuget.view_nugetremote",
                ],
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.delete_nugetremote",
                    "has_model_or_domain_or_obj_perms:nuget.view_nugetremote",
                ],
            },
            {
                "action": ["list_roles", "add_role", "remove_role"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": ["has_model_or_domain_or_obj_perms:nuget.manage_roles_nugetremote"],
            },
        ],
        "creation_hooks": [
            {
                "function": "add_roles_for_object_creator",
                "parameters": {"roles": "nuget.nugetremote_owner"},
            },
        ],
        "queryset_scoping": {"function": "scope_queryset"},
    }
    LOCKED_ROLES = {
        "nuget.nugetremote_creator": ["nuget.add_nugetremote"],
        "nuget.nugetremote_owner": [
            "nuget.view_nugetremote",
            "nuget.change_nugetremote",
            "nuget.delete_nugetremote",
            "nuget.manage_roles_nugetremote",
        ],
        "nuget.nugetremote_viewer": ["nuget.view_nugetremote"],
    }


class NugetRepositoryViewSet(core.RepositoryViewSet, ModifyRepositoryActionMixin, core.RolesMixin):
    """
    A ViewSet for NugetRepository.
    """

    endpoint_name = "nuget"
    queryset = models.NugetRepository.objects.all()
    serializer_class = serializers.NugetRepositorySerializer
    queryset_filtering_required_permission = "nuget.view_nugetrepository"

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "my_permissions"],
                "principal": "authenticated",
                "effect": "allow",
            },
            {
                "action": ["create"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_perms:nuget.add_nugetrepository",
                    "has_remote_param_model_or_domain_or_obj_perms:nuget.view_nugetremote",
                ],
            },
            {
                "action": ["retrieve"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:nuget.view_nugetrepository",
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.delete_nugetrepository",
                    "has_model_or_domain_or_obj_perms:nuget.view_nugetrepository",
                ],
            },
            {
                "action": ["update", "partial_update", "set_label", "unset_label"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.change_nugetrepository",
                    "has_model_or_domain_or_obj_perms:nuget.view_nugetrepository",
                    "has_remote_param_model_or_domain_or_obj_perms:nuget.view_nugetremote",
                ],
            },
            {
                "action": ["sync"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.sync_nugetrepository",
                    "has_model_or_domain_or_obj_perms:nuget.view_nugetrepository",
                    "has_remote_param_model_or_domain_or_obj_perms:nuget.view_nugetremote",
                ],
            },
            {
                "action": ["modify"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.modify_nugetrepository",
                    "has_model_or_domain_or_obj_perms:nuget.view_nugetrepository",
                ],
            },
            {
                "action": ["list_roles", "add_role", "remove_role"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.manage_roles_nugetrepository"
                ],
            },
        ],
        "creation_hooks": [
            {
                "function": "add_roles_for_object_creator",
                "parameters": {"roles": "nuget.nugetrepository_owner"},
            },
        ],
        "queryset_scoping": {"function": "scope_queryset"},
    }
    LOCKED_ROLES = {
        "nuget.nugetrepository_creator": ["nuget.add_nugetrepository"],
        "nuget.nugetrepository_owner": [
            "nuget.view_nugetrepository",
            "nuget.change_nugetrepository",
            "nuget.delete_nugetrepository",
            "nuget.modify_nugetrepository",
            "nuget.sync_nugetrepository",
            "nuget.manage_roles_nugetrepository",
            "nuget.repair_nugetrepository",
        ],
        "nuget.nugetrepository_viewer": ["nuget.view_nugetrepository"],
    }

    @extend_schema(
        description="Trigger an asynchronous task to sync content from a NuGet v3 feed.",
        summary="Sync from remote",
        responses={202: AsyncOperationResponseSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        serializer_class=serializers.NugetRepositorySyncURLSerializer,
    )
    def sync(self, request, pk):
        """
        Dispatches a sync task.
        """
        repository = self.get_object()
        serializer = serializers.NugetRepositorySyncURLSerializer(
            data=request.data, context={"request": request, "repository_pk": pk}
        )
        serializer.is_valid(raise_exception=True)
        remote = serializer.validated_data.get("remote", repository.remote)
        mirror = serializer.validated_data.get("mirror", False)
        optimize = serializer.validated_data.get("optimize", True)

        result = dispatch(
            tasks.synchronize,
            shared_resources=[remote],
            exclusive_resources=[repository],
            kwargs={
                "remote_pk": str(remote.pk),
                "repository_pk": str(repository.pk),
                "mirror": mirror,
                "optimize": optimize,
            },
        )
        return core.OperationPostponedResponse(result, request)


class NugetRepositoryVersionViewSet(core.RepositoryVersionViewSet):
    """
    A ViewSet for NugetRepositoryVersion.
    """

    parent_viewset = NugetRepositoryViewSet

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "retrieve"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": (
                    "has_repository_model_or_domain_or_obj_perms:nuget.view_nugetrepository"
                ),
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_repository_model_or_domain_or_obj_perms:nuget.delete_nugetrepository",
                    "has_repository_model_or_domain_or_obj_perms:nuget.view_nugetrepository",
                ],
            },
            {
                "action": ["repair"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_repository_model_or_domain_or_obj_perms:nuget.repair_nugetrepository",
                    "has_repository_model_or_domain_or_obj_perms:nuget.view_nugetrepository",
                ],
            },
        ],
    }


class NugetContentGuardViewSet(core.ContentGuardViewSet, core.RolesMixin):
    """
    A ViewSet for NugetContentGuard.

    Protects a distribution with HTTP basic auth in a way NuGet clients understand:
    anonymous requests get a 401 ``WWW-Authenticate: Basic`` challenge, and authenticated
    users need the download permission (grant ``nuget.nugetcontentguard_downloader``).
    """

    endpoint_name = "nuget"
    queryset = models.NugetContentGuard.objects.all()
    serializer_class = serializers.NugetContentGuardSerializer
    queryset_filtering_required_permission = "nuget.view_nugetcontentguard"

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "my_permissions"],
                "principal": "authenticated",
                "effect": "allow",
            },
            {
                "action": ["create"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_perms:nuget.add_nugetcontentguard",
            },
            {
                "action": ["retrieve"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:nuget.view_nugetcontentguard",
            },
            {
                "action": ["update", "partial_update", "set_label", "unset_label"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.change_nugetcontentguard",
                    "has_model_or_domain_or_obj_perms:nuget.view_nugetcontentguard",
                ],
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.delete_nugetcontentguard",
                    "has_model_or_domain_or_obj_perms:nuget.view_nugetcontentguard",
                ],
            },
            {
                "action": ["list_roles", "add_role", "remove_role"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.manage_roles_nugetcontentguard"
                ],
            },
        ],
        "creation_hooks": [
            {
                "function": "add_roles_for_object_creator",
                "parameters": {"roles": "nuget.nugetcontentguard_owner"},
            },
        ],
        "queryset_scoping": {"function": "scope_queryset"},
    }
    LOCKED_ROLES = {
        "nuget.nugetcontentguard_creator": ["nuget.add_nugetcontentguard"],
        "nuget.nugetcontentguard_owner": [
            "nuget.view_nugetcontentguard",
            "nuget.change_nugetcontentguard",
            "nuget.delete_nugetcontentguard",
            "nuget.download_nugetcontentguard",
            "nuget.manage_roles_nugetcontentguard",
        ],
        "nuget.nugetcontentguard_viewer": ["nuget.view_nugetcontentguard"],
        # Grant this (at model, domain, or object level) to allow downloading from
        # distributions protected by the guard.
        "nuget.nugetcontentguard_downloader": ["nuget.download_nugetcontentguard"],
    }


class NugetDistributionViewSet(core.DistributionViewSet, core.RolesMixin):
    """
    A ViewSet for NugetDistribution.

    The distribution serves a live NuGet v3 API; point clients at
    ``<base_url>/v3/index.json``.
    """

    endpoint_name = "nuget"
    queryset = models.NugetDistribution.objects.all()
    serializer_class = serializers.NugetDistributionSerializer
    queryset_filtering_required_permission = "nuget.view_nugetdistribution"

    DEFAULT_ACCESS_POLICY = {
        "statements": [
            {
                "action": ["list", "my_permissions"],
                "principal": "authenticated",
                "effect": "allow",
            },
            {
                "action": ["create"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_perms:nuget.add_nugetdistribution",
                    "has_repo_or_repo_ver_param_model_or_domain_or_obj_perms:"
                    "nuget.view_nugetrepository",
                ],
            },
            {
                "action": ["retrieve"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": "has_model_or_domain_or_obj_perms:nuget.view_nugetdistribution",
            },
            {
                "action": ["update", "partial_update", "set_label", "unset_label"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.change_nugetdistribution",
                    "has_model_or_domain_or_obj_perms:nuget.view_nugetdistribution",
                    "has_repo_or_repo_ver_param_model_or_domain_or_obj_perms:"
                    "nuget.view_nugetrepository",
                ],
            },
            {
                "action": ["destroy"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.delete_nugetdistribution",
                    "has_model_or_domain_or_obj_perms:nuget.view_nugetdistribution",
                ],
            },
            {
                "action": ["list_roles", "add_role", "remove_role"],
                "principal": "authenticated",
                "effect": "allow",
                "condition": [
                    "has_model_or_domain_or_obj_perms:nuget.manage_roles_nugetdistribution"
                ],
            },
        ],
        "creation_hooks": [
            {
                "function": "add_roles_for_object_creator",
                "parameters": {"roles": "nuget.nugetdistribution_owner"},
            },
        ],
        "queryset_scoping": {"function": "scope_queryset"},
    }
    LOCKED_ROLES = {
        "nuget.nugetdistribution_creator": ["nuget.add_nugetdistribution"],
        "nuget.nugetdistribution_owner": [
            "nuget.view_nugetdistribution",
            "nuget.change_nugetdistribution",
            "nuget.delete_nugetdistribution",
            "nuget.publish_nugetdistribution",
            "nuget.manage_roles_nugetdistribution",
        ],
        "nuget.nugetdistribution_viewer": ["nuget.view_nugetdistribution"],
        # Grant this (at model, domain, or object level) to allow dotnet nuget push,
        # delete (unlist), and relist against the distribution's publish endpoint.
        "nuget.nugetdistribution_publisher": ["nuget.publish_nugetdistribution"],
    }
