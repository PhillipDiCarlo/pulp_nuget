"""Import/export resources for pulp_nuget (PulpExporter/PulpImporter support)."""

from pulpcore.plugin.importexport import BaseContentResource
from pulpcore.plugin.modelresources import RepositoryResource

from pulp_nuget.app.models import (
    NugetPackageContent,
    NugetRepository,
    NugetSymbolPackageContent,
)


class NugetContentResource(BaseContentResource):
    """Shared base for pulp_nuget content resources."""

    def dehydrate__pulp_domain(self, content):
        return str(content._pulp_domain_id)


class NugetPackageContentResource(NugetContentResource):
    """Resource for import/export of nuget_nugetpackagecontent entities."""

    def set_up_queryset(self):
        """The packages in the repository version being exported."""
        return NugetPackageContent.objects.filter(pk__in=self.repo_version.content).order_by(
            "content_ptr_id"
        )

    class Meta:
        model = NugetPackageContent
        import_id_fields = model.natural_key_fields()


class NugetSymbolPackageContentResource(NugetContentResource):
    """Resource for import/export of nuget_nugetsymbolpackagecontent entities."""

    def set_up_queryset(self):
        """The symbol packages in the repository version being exported."""
        return NugetSymbolPackageContent.objects.filter(pk__in=self.repo_version.content).order_by(
            "content_ptr_id"
        )

    class Meta:
        model = NugetSymbolPackageContent
        import_id_fields = model.natural_key_fields()


class NugetRepositoryResource(RepositoryResource):
    """Resource for import/export of nuget repository entities."""

    def set_up_queryset(self):
        """The repository being exported."""
        return NugetRepository.objects.filter(pk=self.repo_version.repository)

    class Meta:
        model = NugetRepository
        # last_sync_details records the source instance's remote pk and upstream
        # checksums; carrying it over would defeat sync optimization's change checks.
        exclude = RepositoryResource.Meta.exclude + ("last_sync_details",)


IMPORT_ORDER = [
    NugetRepositoryResource,
    NugetPackageContentResource,
    NugetSymbolPackageContentResource,
]
