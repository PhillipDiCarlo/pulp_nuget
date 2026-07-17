"""Functional tests for the retain_package_versions retention policy."""

import uuid


def _repo_versions(nuget_bindings, repo, **kwargs):
    repository = nuget_bindings.RepositoriesNugetApi.read(repo.pulp_href)
    packages = nuget_bindings.ContentPackagesApi.list(
        repository_version=repository.latest_version_href, limit=100, **kwargs
    )
    return {package.version_normalized for package in packages.results}


def test_retention_on_upload(
    nuget_bindings,
    gen_object_with_cleanup,
    nupkg_factory,
    package_upload_factory,
):
    """Each new repository version keeps only the newest N versions of a package id."""
    repo = gen_object_with_cleanup(
        nuget_bindings.RepositoriesNugetApi,
        {"name": str(uuid.uuid4()), "retain_package_versions": 2},
    )
    package_id = f"Pulp.Retention.{uuid.uuid4().hex[:8]}"

    for version in ("1.0.0", "1.1.0"):
        package_upload_factory(nupkg_factory(package_id, version), repository=repo.pulp_href)
    assert _repo_versions(nuget_bindings, repo) == {"1.0.0", "1.1.0"}

    # A third version pushes the oldest one out of the new repository version.
    package_upload_factory(nupkg_factory(package_id, "2.0.0"), repository=repo.pulp_href)
    assert _repo_versions(nuget_bindings, repo) == {"1.1.0", "2.0.0"}

    # An older version than the retained ones is dropped again immediately.
    package_upload_factory(nupkg_factory(package_id, "0.9.0"), repository=repo.pulp_href)
    assert _repo_versions(nuget_bindings, repo) == {"1.1.0", "2.0.0"}


def test_retention_applies_to_symbol_packages(
    nuget_bindings,
    gen_object_with_cleanup,
    snupkg_factory,
    portable_pdb_factory,
    monitor_task,
):
    """Symbol packages are retained per package id like regular packages."""
    repo = gen_object_with_cleanup(
        nuget_bindings.RepositoriesNugetApi,
        {"name": str(uuid.uuid4()), "retain_package_versions": 1},
    )
    package_id = f"Pulp.Retention.{uuid.uuid4().hex[:8]}"
    for version in ("1.0.0", "1.1.0"):
        pdb, _ = portable_pdb_factory()
        path = snupkg_factory(package_id, version, [(f"lib/{package_id}.pdb", pdb)])
        monitor_task(
            nuget_bindings.ContentSymbolPackagesApi.create(
                file=path, repository=repo.pulp_href
            ).task
        )

    repository = nuget_bindings.RepositoriesNugetApi.read(repo.pulp_href)
    symbol_packages = nuget_bindings.ContentSymbolPackagesApi.list(
        repository_version=repository.latest_version_href
    )
    assert [package.version_normalized for package in symbol_packages.results] == ["1.1.0"]


def test_retention_on_sync(nuget_bindings, gen_object_with_cleanup, remote_factory, sync):
    """A sync honors the repository's retention policy."""
    repo = gen_object_with_cleanup(
        nuget_bindings.RepositoriesNugetApi,
        {"name": str(uuid.uuid4()), "retain_package_versions": 2},
    )
    remote = remote_factory(includes=["Newtonsoft.Json.Bson [1.0.1, 1.0.3]"])
    sync(repo, remote)
    assert _repo_versions(nuget_bindings, repo) == {"1.0.2", "1.0.3"}
