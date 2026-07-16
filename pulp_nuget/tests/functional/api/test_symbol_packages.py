"""Functional tests for .snupkg symbol packages: push, serving, and the symbol server."""

import uuid

import pytest
import requests


def _resource_url(distribution, distribution_url_factory, resource_type):
    response = requests.get(distribution_url_factory(distribution, "v3/index.json"))
    response.raise_for_status()
    return next(
        resource["@id"]
        for resource in response.json()["resources"]
        if resource["@type"] == resource_type
    )


def test_symbol_package_push_and_symbol_server(
    nuget_bindings,
    nuget_repo,
    nuget_distribution_factory,
    distribution_url_factory,
    snupkg_factory,
    portable_pdb_factory,
    bindings_cfg,
    monitor_task,
    anon_session,
):
    """A .snupkg pushed to SymbolPackagePublish is served back, PDBs via SSQP keys."""
    distribution = nuget_distribution_factory(repository=nuget_repo.pulp_href)
    push_url = _resource_url(distribution, distribution_url_factory, "SymbolPackagePublish/4.9.0")

    # Content dedup is by (id, version) natural key, so reuse across test runs against
    # a persistent dev instance would return stale content — make the id unique.
    package_id = f"Pulp.Symbols.{uuid.uuid4().hex[:8]}"
    pdb, signature = portable_pdb_factory()
    snupkg_path = snupkg_factory(package_id, "1.0.0", [(f"lib/net8.0/{package_id}.pdb", pdb)])

    # Anonymous pushes are rejected.
    with open(snupkg_path, "rb") as fp:
        assert anon_session.put(push_url + "/", files={"package": fp}).status_code == 401

    # NuGet clients PUT with a trailing slash appended to the advertised URL.
    with open(snupkg_path, "rb") as fp:
        response = requests.put(
            push_url + "/",
            files={"package": fp},
            auth=(bindings_cfg.username, bindings_cfg.password),
        )
    assert response.status_code == 202, response.text
    monitor_task(response.json()["task"])

    repository = nuget_bindings.RepositoriesNugetApi.read(nuget_repo.pulp_href)
    symbol_packages = nuget_bindings.ContentSymbolPackagesApi.list(
        repository_version=repository.latest_version_href
    )
    assert symbol_packages.count == 1
    symbol_package = symbol_packages.results[0]
    assert symbol_package.package_id == package_id
    assert symbol_package.version_normalized == "1.0.0"
    id_lower = package_id.lower()
    assert symbol_package.pdb_files == [
        {
            "path": f"lib/net8.0/{package_id}.pdb",
            "name": f"{id_lower}.pdb",
            "signature": signature,
        }
    ]

    # The SSQP symbol server hands the PDB to debuggers by filename and signature...
    response = requests.get(
        distribution_url_factory(
            distribution, f"symbols/{id_lower}.pdb/{signature}/{id_lower}.pdb"
        )
    )
    response.raise_for_status()
    assert response.content == pdb
    assert response.headers["Content-Type"] == "application/octet-stream"

    # ...and 404s for an unknown signature.
    wrong_signature = "0" * 32 + "ffffffff"
    response = requests.get(
        distribution_url_factory(
            distribution,
            f"symbols/{id_lower}.pdb/{wrong_signature}/{id_lower}.pdb",
        )
    )
    assert response.status_code == 404

    # The .snupkg itself is downloadable from the flat container.
    response = requests.get(
        distribution_url_factory(
            distribution,
            f"v3-flatcontainer/{id_lower}/1.0.0/{id_lower}.1.0.0.snupkg",
        )
    )
    response.raise_for_status()
    assert response.content[:2] == b"PK"


def test_symbol_package_upload_is_idempotent(
    nuget_bindings, snupkg_factory, portable_pdb_factory, monitor_task
):
    """Uploading the same .snupkg twice returns the same content unit."""
    package_id = f"Pulp.Symbols.{uuid.uuid4().hex[:8]}"
    pdb, _ = portable_pdb_factory()
    path = snupkg_factory(package_id, "2.1.0", [(f"lib/{package_id}.pdb", pdb)])

    def upload():
        response = nuget_bindings.ContentSymbolPackagesApi.create(file=path)
        task = monitor_task(response.task)
        return next(
            resource
            for resource in task.created_resources
            if "content/nuget/symbol_packages/" in resource
        )

    assert upload() == upload()


def test_symbol_package_upload_rejects_regular_nupkg(
    nuget_bindings, pulpcore_bindings, nuget_repo, nupkg_factory, monitor_task
):
    """A plain .nupkg (no SymbolsPackage type, no PDBs) fails symbol-package validation."""
    path = nupkg_factory("plain.pkg", "1.0.0")
    task_href = nuget_bindings.ContentSymbolPackagesApi.create(
        file=path, repository=nuget_repo.pulp_href
    ).task
    with pytest.raises(Exception):
        monitor_task(task_href)
    task = pulpcore_bindings.TasksApi.read(task_href)
    assert task.state == "failed"
    assert "symbol package" in task.error["description"]
