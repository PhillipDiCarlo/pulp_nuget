"""Functional tests for the '*' wildcard allowlist and Pulp-to-Pulp replication."""

import uuid

import pydantic
import pytest


@pytest.fixture
def upstream_feed(
    nuget_bindings,
    gen_object_with_cleanup,
    nupkg_factory,
    package_upload_factory,
    nuget_distribution_factory,
):
    """A distribution serving a repository with two synthetic packages."""
    repository = gen_object_with_cleanup(
        nuget_bindings.RepositoriesNugetApi, {"name": str(uuid.uuid4())}
    )
    prefix = f"Pulp.Replica.{uuid.uuid4().hex[:8]}"
    package_ids = [f"{prefix}.A", f"{prefix}.B"]
    for package_id in package_ids:
        package_upload_factory(nupkg_factory(package_id, "1.0.0"), repository=repository.pulp_href)
    distribution = nuget_distribution_factory(repository=repository.pulp_href)
    return distribution, package_ids


def _repo_package_ids(nuget_bindings, repository_href):
    repository = nuget_bindings.RepositoriesNugetApi.read(repository_href)
    packages = nuget_bindings.ContentPackagesApi.list(
        repository_version=repository.latest_version_href, limit=100
    )
    return {package.package_id for package in packages.results}


def test_wildcard_sync(
    nuget_bindings, nuget_repo, remote_factory, sync, upstream_feed, monitor_task
):
    """includes=['*'] mirrors everything the upstream feed's search enumerates."""
    distribution, package_ids = upstream_feed
    remote = remote_factory(
        url=distribution.base_url + "v3/index.json",
        includes=["*"],
        policy="immediate",
        tls_validation=False,
    )

    sync(nuget_repo, remote, mirror=True)
    assert _repo_package_ids(nuget_bindings, nuget_repo.pulp_href) == set(package_ids)

    # Excludes still apply on top of the wildcard.
    monitor_task(
        nuget_bindings.RemotesNugetApi.partial_update(
            remote.pulp_href, {"excludes": [package_ids[0]]}
        ).task
    )
    sync(nuget_repo, remote, mirror=True)
    assert _repo_package_ids(nuget_bindings, nuget_repo.pulp_href) == {package_ids[1]}


def test_wildcard_must_be_alone(nuget_bindings, remote_factory):
    """'*' combined with other includes entries is rejected."""
    with pytest.raises(nuget_bindings.module.ApiException) as exc:
        remote_factory(includes=["*", "Serilog"])
    assert exc.value.status == 400
    assert "must be the only includes entry" in exc.value.body


def test_replicate_from_upstream_pulp(
    nuget_bindings,
    pulpcore_bindings,
    gen_object_with_cleanup,
    upstream_feed,
    bindings_cfg,
    monitor_task,
    monitor_task_group,
):
    """Replication mirrors an upstream Pulp's nuget distribution onto this instance."""
    distribution, package_ids = upstream_feed

    server = gen_object_with_cleanup(
        pulpcore_bindings.UpstreamPulpsApi,
        {
            "name": str(uuid.uuid4()),
            "base_url": bindings_cfg.host,
            "api_root": "/pulp/",
            "username": bindings_cfg.username,
            "password": bindings_cfg.password,
            "tls_validation": False,
            # Scope the replication to just our upstream distribution.
            "q_select": f'name="{distribution.name}"',
        },
    )
    try:
        response = pulpcore_bindings.UpstreamPulpsApi.replicate(server.pulp_href, {})
    except (TypeError, pydantic.ValidationError):
        # pulpcore < 3.113: the replicate action takes no request body.
        response = pulpcore_bindings.UpstreamPulpsApi.replicate(server.pulp_href)
    monitor_task_group(response.task_group)

    # Replication created a remote and a repository named after the distribution.
    remotes = nuget_bindings.RemotesNugetApi.list(name=distribution.name)
    assert remotes.count == 1
    remote = remotes.results[0]
    assert remote.includes == ["*"]
    assert remote.url == distribution.base_url.rstrip("/") + "/v3/index.json"

    replica_repos = nuget_bindings.RepositoriesNugetApi.list(name=distribution.name)
    assert replica_repos.count == 1
    replica_repo = replica_repos.results[0]
    assert _repo_package_ids(nuget_bindings, replica_repo.pulp_href) == set(package_ids)

    # The distribution now serves the replica repository (pinned to its latest version).
    refreshed = nuget_bindings.DistributionsNugetApi.read(distribution.pulp_href)
    replica_repo = nuget_bindings.RepositoriesNugetApi.read(replica_repo.pulp_href)
    assert refreshed.repository is None
    assert refreshed.repository_version == replica_repo.latest_version_href

    # Clean up what replication created (the distribution's fixture cleans itself up).
    monitor_task(nuget_bindings.RepositoriesNugetApi.delete(replica_repo.pulp_href).task)
    monitor_task(nuget_bindings.RemotesNugetApi.delete(remote.pulp_href).task)
