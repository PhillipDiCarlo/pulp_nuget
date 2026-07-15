"""Functional tests: upload a .nupkg, serve the v3 API, and sync from an upstream feed."""

import uuid

import pytest
import requests


def test_upload_parses_nuspec_metadata(newtonsoft_package_factory, monitor_task):
    """Uploading a real .nupkg parses the embedded .nuspec into content metadata."""
    package = newtonsoft_package_factory()

    assert package.package_id == "Newtonsoft.Json"
    assert package.version == "13.0.3"
    assert package.version_normalized == "13.0.3"
    assert package.authors == "James Newton-King"
    assert package.license_expression == "MIT"
    assert package.min_client_version == "2.12"
    assert package.sha512 is not None
    target_frameworks = {group["targetFramework"] for group in package.dependency_groups}
    assert ".NETStandard2.0" in target_frameworks


def test_upload_is_idempotent(newtonsoft_package_factory):
    """Uploading the same package twice returns the same content unit."""
    first = newtonsoft_package_factory()
    second = newtonsoft_package_factory()
    assert first.pulp_href == second.pulp_href


def test_serve_v3_api(
    nuget_bindings,
    nuget_repo,
    newtonsoft_package_factory,
    nuget_distribution_factory,
    distribution_url_factory,
    monitor_task,
):
    """A distribution serves service index, flatcontainer, registrations, and search."""
    newtonsoft_package_factory(repository=nuget_repo.pulp_href)
    distribution = nuget_distribution_factory(repository=nuget_repo.pulp_href)

    # Service index advertises the required resources with absolute URLs.
    response = requests.get(distribution_url_factory(distribution, "v3/index.json"))
    response.raise_for_status()
    service_index = response.json()
    assert service_index["version"] == "3.0.0"
    types = {resource["@type"] for resource in service_index["resources"]}
    assert {"PackageBaseAddress/3.0.0", "RegistrationsBaseUrl", "SearchQueryService"} <= types
    for resource in service_index["resources"]:
        assert resource["@id"].startswith("http"), resource

    # Flat container: version list and package download.
    response = requests.get(
        distribution_url_factory(distribution, "v3-flatcontainer/newtonsoft.json/index.json")
    )
    response.raise_for_status()
    assert response.json() == {"versions": ["13.0.3"]}

    response = requests.get(
        distribution_url_factory(
            distribution,
            "v3-flatcontainer/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg",
        )
    )
    response.raise_for_status()
    assert len(response.content) > 1000
    assert response.content[:2] == b"PK"

    # Registrations: index and leaf with a well-formed catalogEntry.
    response = requests.get(
        distribution_url_factory(distribution, "v3/registrations/newtonsoft.json/index.json")
    )
    response.raise_for_status()
    registration_index = response.json()
    assert registration_index["count"] == 1
    page = registration_index["items"][0]
    assert page["lower"] == "13.0.3"
    assert page["upper"] == "13.0.3"
    leaf = page["items"][0]
    entry = leaf["catalogEntry"]
    assert entry["id"] == "Newtonsoft.Json"
    assert entry["version"] == "13.0.3"
    assert leaf["packageContent"].endswith("newtonsoft.json.13.0.3.nupkg")
    dependencies = [
        dependency
        for group in entry["dependencyGroups"]
        for dependency in group.get("dependencies", [])
    ]
    for dependency in dependencies:
        assert dependency["range"].startswith(("[", "(")), dependency

    response = requests.get(
        distribution_url_factory(distribution, "v3/registrations/newtonsoft.json/13.0.3.json")
    )
    response.raise_for_status()
    assert response.json()["catalogEntry"]["id"] == "Newtonsoft.Json"

    # Search finds the package and respects paging.
    response = requests.get(
        distribution_url_factory(distribution, "v3/search"), params={"q": "newtonsoft"}
    )
    response.raise_for_status()
    results = response.json()
    assert results["totalHits"] == 1
    assert results["data"][0]["id"] == "Newtonsoft.Json"

    response = requests.get(
        distribution_url_factory(distribution, "v3/search"), params={"q": "nomatch-xyz"}
    )
    response.raise_for_status()
    assert response.json() == {"totalHits": 0, "data": []}

    # Unknown ids 404 on the metadata endpoints.
    response = requests.get(
        distribution_url_factory(distribution, "v3-flatcontainer/does.not.exist/index.json")
    )
    assert response.status_code == 404


def test_sync_from_nuget_org(
    nuget_bindings,
    nuget_repo,
    gen_object_with_cleanup,
    nuget_distribution_factory,
    distribution_url_factory,
    monitor_task,
):
    """Sync an allowlisted package id from nuget.org with policy=on_demand."""
    remote = gen_object_with_cleanup(
        nuget_bindings.RemotesNugetApi,
        {
            "name": str(uuid.uuid4()),
            "url": "https://api.nuget.org/v3/index.json",
            "policy": "on_demand",
            "includes": ["Newtonsoft.Json.Bson"],
        },
    )

    task = nuget_bindings.RepositoriesNugetApi.sync(
        nuget_repo.pulp_href, {"remote": remote.pulp_href}
    ).task
    monitor_task(task)

    repository = nuget_bindings.RepositoriesNugetApi.read(nuget_repo.pulp_href)
    packages = nuget_bindings.ContentPackagesApi.list(
        repository_version=repository.latest_version_href, limit=100
    )
    assert packages.count > 0
    assert all(package.package_id == "Newtonsoft.Json.Bson" for package in packages.results)

    # An on_demand package streams through the distribution on first request.
    distribution = nuget_distribution_factory(repository=nuget_repo.pulp_href)
    version = packages.results[0].version_normalized
    response = requests.get(
        distribution_url_factory(
            distribution,
            f"v3-flatcontainer/newtonsoft.json.bson/{version}/newtonsoft.json.bson.{version}.nupkg",
        )
    )
    response.raise_for_status()
    assert response.content[:2] == b"PK"


def test_package_push(
    nuget_bindings,
    nuget_repo,
    nuget_distribution_factory,
    distribution_url_factory,
    newtonsoft_nupkg_path,
    bindings_cfg,
    monitor_task,
):
    """A .nupkg can be pushed to the PackagePublish endpoint from the service index."""
    distribution = nuget_distribution_factory(repository=nuget_repo.pulp_href)

    response = requests.get(distribution_url_factory(distribution, "v3/index.json"))
    response.raise_for_status()
    publish_url = next(
        resource["@id"]
        for resource in response.json()["resources"]
        if resource["@type"] == "PackagePublish/2.0.0"
    )

    # Anonymous pushes are rejected.
    with open(newtonsoft_nupkg_path, "rb") as fp:
        response = requests.put(publish_url, files={"package": fp})
    assert response.status_code == 401

    # NuGet clients PUT with a trailing slash appended to the advertised URL.
    with open(newtonsoft_nupkg_path, "rb") as fp:
        response = requests.put(
            publish_url + "/",
            files={"package": fp},
            auth=(bindings_cfg.username, bindings_cfg.password),
        )
    assert response.status_code == 202, response.text
    monitor_task(response.json()["task"])

    repository = nuget_bindings.RepositoriesNugetApi.read(nuget_repo.pulp_href)
    packages = nuget_bindings.ContentPackagesApi.list(
        repository_version=repository.latest_version_href
    )
    assert packages.count == 1
    assert packages.results[0].package_id == "Newtonsoft.Json"


def _publish_url(distribution, distribution_url_factory):
    response = requests.get(distribution_url_factory(distribution, "v3/index.json"))
    response.raise_for_status()
    return next(
        resource["@id"]
        for resource in response.json()["resources"]
        if resource["@type"] == "PackagePublish/2.0.0"
    )


def test_flatcontainer_nuspec(
    nuget_repo,
    newtonsoft_package_factory,
    nuget_distribution_factory,
    distribution_url_factory,
):
    """The flat container serves the raw .nuspec manifest extracted from the .nupkg."""
    newtonsoft_package_factory(repository=nuget_repo.pulp_href)
    distribution = nuget_distribution_factory(repository=nuget_repo.pulp_href)

    response = requests.get(
        distribution_url_factory(
            distribution, "v3-flatcontainer/newtonsoft.json/13.0.3/newtonsoft.json.nuspec"
        )
    )
    response.raise_for_status()
    assert b"<id>Newtonsoft.Json</id>" in response.content

    # The manifest filename carries no version; the versioned form is not a real path.
    response = requests.get(
        distribution_url_factory(
            distribution, "v3-flatcontainer/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nuspec"
        )
    )
    assert response.status_code == 404


def test_unlist_and_relist(
    nuget_repo,
    newtonsoft_package_factory,
    nuget_distribution_factory,
    distribution_url_factory,
    bindings_cfg,
):
    """DELETE on the publish endpoint unlists a package; POST relists it."""
    newtonsoft_package_factory(repository=nuget_repo.pulp_href)
    distribution = nuget_distribution_factory(repository=nuget_repo.pulp_href)
    delete_url = f"{_publish_url(distribution, distribution_url_factory)}/Newtonsoft.Json/13.0.3"
    auth = (bindings_cfg.username, bindings_cfg.password)
    search_url = distribution_url_factory(distribution, "v3/search")

    assert requests.delete(delete_url).status_code == 401

    try:
        assert requests.delete(delete_url, auth=auth).status_code == 204

        # Hidden from search, marked unlisted in registrations...
        assert requests.get(search_url).json()["totalHits"] == 0
        leaf = requests.get(
            distribution_url_factory(distribution, "v3/registrations/newtonsoft.json/13.0.3.json")
        ).json()
        assert leaf["listed"] is False
        assert leaf["catalogEntry"]["listed"] is False

        # ...but still enumerable and downloadable by exact version.
        response = requests.get(
            distribution_url_factory(distribution, "v3-flatcontainer/newtonsoft.json/index.json")
        )
        assert response.json() == {"versions": ["13.0.3"]}
        response = requests.get(
            distribution_url_factory(
                distribution,
                "v3-flatcontainer/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg",
            )
        )
        assert response.status_code == 200

        # Unknown package versions 404.
        response = requests.delete(f"{delete_url[: -len('13.0.3')]}9.9.9", auth=auth)
        assert response.status_code == 404
    finally:
        # Relist even on failure: the flag is global on the content unit.
        assert requests.post(delete_url, auth=auth).status_code == 200

    assert requests.get(search_url).json()["totalHits"] == 1


def test_search_package_type_and_semver_level(
    nuget_repo,
    nupkg_factory,
    package_upload_factory,
    nuget_distribution_factory,
    distribution_url_factory,
):
    """Search honors the packageType and semVerLevel query parameters."""
    for package_id, version, package_type in (
        ("Pulp.Test.Tool", "1.0.0", "DotnetTool"),
        ("Pulp.Test.Lib", "1.0.0", None),
        ("Pulp.Test.Semver2", "1.0.0-beta.1", None),
    ):
        package_upload_factory(
            nupkg_factory(package_id, version, package_type), repository=nuget_repo.pulp_href
        )
    distribution = nuget_distribution_factory(repository=nuget_repo.pulp_href)
    search_url = distribution_url_factory(distribution, "v3/search")

    def ids(**params):
        response = requests.get(search_url, params=params)
        response.raise_for_status()
        return {entry["id"] for entry in response.json()["data"]}

    assert ids() == {"Pulp.Test.Tool", "Pulp.Test.Lib"}
    assert ids(packageType="DotnetTool") == {"Pulp.Test.Tool"}
    # Matching is case-insensitive; no declared type means the implicit Dependency type.
    assert ids(packageType="dependency") == {"Pulp.Test.Lib"}
    assert ids(packageType="NoSuchType") == set()
    # A dotted prerelease label is SemVer2: hidden unless semVerLevel=2.0.0.
    assert ids(prerelease="true") == {"Pulp.Test.Tool", "Pulp.Test.Lib"}
    assert ids(prerelease="true", semVerLevel="2.0.0") == {
        "Pulp.Test.Tool",
        "Pulp.Test.Lib",
        "Pulp.Test.Semver2",
    }

    response = requests.get(search_url, params={"packageType": "DotnetTool"})
    assert response.json()["data"][0]["packageTypes"] == [{"name": "DotnetTool"}]


def test_sync_requires_includes(
    nuget_bindings, pulpcore_bindings, nuget_repo, gen_object_with_cleanup, monitor_task
):
    """Syncing a remote with an empty allowlist fails with a useful error."""
    remote = gen_object_with_cleanup(
        nuget_bindings.RemotesNugetApi,
        {
            "name": str(uuid.uuid4()),
            "url": "https://api.nuget.org/v3/index.json",
            "includes": [],
        },
    )
    task_href = nuget_bindings.RepositoriesNugetApi.sync(
        nuget_repo.pulp_href, {"remote": remote.pulp_href}
    ).task
    with pytest.raises(Exception):
        monitor_task(task_href)
    task = pulpcore_bindings.TasksApi.read(task_href)
    assert task.state == "failed"
    assert "includes" in task.error["description"]
