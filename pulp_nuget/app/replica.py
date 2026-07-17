"""Replication support: mirror the nuget distributions of an upstream Pulp instance."""

from gettext import gettext as _

from pulp_glue.common.context import PulpDistributionContext, PulpRepositoryContext

from pulpcore.plugin.replica import Replicator

from pulp_nuget.app.models import NugetDistribution, NugetRemote, NugetRepository
from pulp_nuget.app.tasks import synchronize


class PulpNugetRepositoryContext(PulpRepositoryContext):
    """pulp_glue context for talking to the upstream's nuget repository endpoints."""

    PLUGIN = "nuget"
    RESOURCE_TYPE = "nuget"
    ENTITY = _("nuget repository")
    ENTITIES = _("nuget repositories")
    HREF = "nuget_nuget_repository_href"
    ID_PREFIX = "repositories_nuget_nuget"


class PulpNugetDistributionContext(PulpDistributionContext):
    """pulp_glue context for talking to the upstream's nuget distribution endpoints."""

    PLUGIN = "nuget"
    RESOURCE_TYPE = "nuget"
    ENTITY = _("nuget distribution")
    ENTITIES = _("nuget distributions")
    HREF = "nuget_nuget_distribution_href"
    ID_PREFIX = "distributions_nuget_nuget"


class NugetReplicator(Replicator):
    """
    Replicate the upstream Pulp's nuget distributions.

    For every nuget distribution on the upstream, replication maintains a remote
    pointed at that distribution's service index (with the '*' wildcard allowlist,
    since a replica mirrors everything the upstream serves), a repository synced in
    mirror mode, and a distribution serving it under the same base_path.
    """

    repository_ctx_cls = PulpNugetRepositoryContext
    distribution_ctx_cls = PulpNugetDistributionContext
    publication_ctx_cls = None
    app_label = "nuget"
    remote_model_cls = NugetRemote
    repository_model_cls = NugetRepository
    distribution_model_cls = NugetDistribution
    distribution_serializer_name = "NugetDistributionSerializer"
    repository_serializer_name = "NugetRepositorySerializer"
    remote_serializer_name = "NugetRemoteSerializer"
    sync_task = synchronize

    def url(self, upstream_distribution):
        """The service index URL of an upstream distribution, or None if it has none."""
        # Only repository(-version) backed distributions serve the v3 API.
        if not upstream_distribution.get("repository") and not upstream_distribution.get(
            "repository_version"
        ):
            return None
        return upstream_distribution["base_url"].rstrip("/") + "/v3/index.json"

    def remote_extra_fields(self, upstream_distribution):
        """A replica mirrors everything the upstream distribution serves."""
        return {"includes": ["*"]}

    def sync_params(self, repository, remote):
        """Sync in mirror mode so removals on the upstream propagate."""
        return dict(
            remote_pk=str(remote.pk),
            repository_pk=str(repository.pk),
            mirror=True,
            optimize=True,
        )


REPLICATION_ORDER = [NugetReplicator]
