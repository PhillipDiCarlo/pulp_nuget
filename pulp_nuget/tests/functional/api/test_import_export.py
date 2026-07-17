"""Functional tests for PulpExporter/PulpImporter support."""

import uuid


def test_export_import_roundtrip(
    nuget_bindings,
    pulpcore_bindings,
    gen_object_with_cleanup,
    nupkg_factory,
    snupkg_factory,
    portable_pdb_factory,
    package_upload_factory,
    monitor_task,
    monitor_task_group,
):
    """A repository version round-trips through export and import into a new repository."""
    source = gen_object_with_cleanup(
        nuget_bindings.RepositoriesNugetApi, {"name": str(uuid.uuid4())}
    )
    package_id = f"Pulp.ImportExport.{uuid.uuid4().hex[:8]}"
    package = package_upload_factory(
        nupkg_factory(package_id, "1.2.3"), repository=source.pulp_href
    )
    pdb, signature = portable_pdb_factory()
    monitor_task(
        nuget_bindings.ContentSymbolPackagesApi.create(
            file=snupkg_factory(package_id, "1.2.3", [(f"lib/{package_id}.pdb", pdb)]),
            repository=source.pulp_href,
        ).task
    )

    exporter = gen_object_with_cleanup(
        pulpcore_bindings.ExportersPulpApi,
        {
            "name": str(uuid.uuid4()),
            "path": f"/tmp/{uuid.uuid4()}/",
            "repositories": [source.pulp_href],
        },
    )
    export_task = monitor_task(
        pulpcore_bindings.ExportersPulpExportsApi.create(exporter.pulp_href, {}).task
    )
    export_href = next(
        resource for resource in export_task.created_resources if "/exports/" in resource
    )
    export = pulpcore_bindings.ExportersPulpExportsApi.read(export_href)
    archive = next(path for path in export.output_file_info if path.endswith((".tar.gz", ".tar")))

    destination = gen_object_with_cleanup(
        nuget_bindings.RepositoriesNugetApi, {"name": str(uuid.uuid4())}
    )
    importer = gen_object_with_cleanup(
        pulpcore_bindings.ImportersPulpApi,
        {"name": str(uuid.uuid4()), "repo_mapping": {source.name: destination.name}},
    )
    import_response = pulpcore_bindings.ImportersPulpImportsApi.create(
        importer.pulp_href, {"path": archive}
    )
    monitor_task_group(import_response.task_group)

    destination = nuget_bindings.RepositoriesNugetApi.read(destination.pulp_href)
    packages = nuget_bindings.ContentPackagesApi.list(
        repository_version=destination.latest_version_href
    )
    assert packages.count == 1
    imported = packages.results[0]
    assert imported.package_id == package_id
    assert imported.version_normalized == "1.2.3"
    assert imported.sha256 == package.sha256
    # On a single instance the import matches the existing unit by natural key.
    assert imported.pulp_href == package.pulp_href

    symbol_packages = nuget_bindings.ContentSymbolPackagesApi.list(
        repository_version=destination.latest_version_href
    )
    assert symbol_packages.count == 1
    assert symbol_packages.results[0].pdb_files == [
        {
            "path": f"lib/{package_id}.pdb",
            "name": f"{package_id.lower()}.pdb",
            "signature": signature,
        }
    ]
