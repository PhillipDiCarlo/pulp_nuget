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


def test_embedded_icon_and_readme(
    nuget_repo,
    nupkg_factory,
    package_upload_factory,
    nuget_distribution_factory,
    distribution_url_factory,
):
    """Embedded icon/readme are served from the flatcontainer and drive iconUrl."""
    png = b"\x89PNG\r\n\x1a\n" + b"fakepixels"
    # Unique ids: content units outlive the test and a different file for a stored id
    # and version is rejected.
    suffix = uuid.uuid4().hex[:8]
    asset_id = f"asset.pkg.{suffix}"
    plain_id = f"plain.pkg.{suffix}"
    path = nupkg_factory(
        asset_id,
        "1.0.0",
        icon=("images/icon.png", png),
        readme=("docs/README.md", b"# Asset Package"),
    )
    package = package_upload_factory(path, repository=nuget_repo.pulp_href)
    assert package.icon_file == "images/icon.png"
    assert package.readme_file == "docs/README.md"
    distribution = nuget_distribution_factory(repository=nuget_repo.pulp_href)

    response = requests.get(
        distribution_url_factory(distribution, f"v3-flatcontainer/{asset_id}/1.0.0/icon")
    )
    response.raise_for_status()
    assert response.headers["Content-Type"].startswith("image/png")
    assert response.content == png

    response = requests.get(
        distribution_url_factory(distribution, f"v3-flatcontainer/{asset_id}/1.0.0/readme")
    )
    response.raise_for_status()
    assert response.headers["Content-Type"].startswith("text/markdown")
    assert response.content == b"# Asset Package"

    # Search and registrations point iconUrl at our endpoint for embedded icons.
    icon_url = distribution_url_factory(distribution, f"v3-flatcontainer/{asset_id}/1.0.0/icon")
    response = requests.get(distribution_url_factory(distribution, "v3/search"))
    assert response.json()["data"][0]["iconUrl"] == icon_url
    response = requests.get(
        distribution_url_factory(distribution, f"v3/registrations/{asset_id}/1.0.0.json")
    )
    assert response.json()["catalogEntry"]["iconUrl"] == icon_url

    # A package without embedded assets 404s on both endpoints.
    plain = nupkg_factory(plain_id, "1.0.0")
    package_upload_factory(plain, repository=nuget_repo.pulp_href)
    for asset in ("icon", "readme"):
        response = requests.get(
            distribution_url_factory(distribution, f"v3-flatcontainer/{plain_id}/1.0.0/{asset}")
        )
        assert response.status_code == 404, asset


def test_remote_filter_validation(nuget_bindings, remote_factory):
    """Malformed includes/excludes entries are rejected when the remote is created."""
    for field in ("includes", "excludes"):
        with pytest.raises(nuget_bindings.module.ApiException) as exc:
            remote_factory(**{field: ["Serilog [2.0"]})
        assert exc.value.status == 400
        assert "Invalid package filter entry" in exc.value.body


def test_sync_version_ranges_and_excludes(nuget_bindings, nuget_repo, remote_factory, sync):
    """Includes may carry version ranges, and excludes filter matching versions out."""
    remote = remote_factory(
        includes=["Newtonsoft.Json.Bson [1.0.1, 1.0.2]"],
        excludes=["Newtonsoft.Json.Bson [1.0.2]"],
    )
    sync(nuget_repo, remote)

    repository = nuget_bindings.RepositoriesNugetApi.read(nuget_repo.pulp_href)
    packages = nuget_bindings.ContentPackagesApi.list(
        repository_version=repository.latest_version_href, limit=100
    )
    versions = {package.version_normalized for package in packages.results}
    assert versions == {"1.0.1"}


def test_sync_optimization(nuget_bindings, nuget_repo, remote_factory, sync, monitor_task):
    """An unchanged remote and upstream skip the sync; optimize=False forces it."""
    remote = remote_factory(includes=["Newtonsoft.Json.Bson [1.0.1, 1.0.2]"])

    first = sync(nuget_repo, remote)
    assert "sync.was_skipped" not in {report.code for report in first.progress_reports}
    repository = nuget_bindings.RepositoriesNugetApi.read(nuget_repo.pulp_href)
    assert repository.last_sync_details["registration_checksums"]

    # Nothing changed: the second sync is skipped and creates no repository version.
    second = sync(nuget_repo, remote)
    assert "sync.was_skipped" in {report.code for report in second.progress_reports}
    assert (
        nuget_bindings.RepositoriesNugetApi.read(nuget_repo.pulp_href).latest_version_href
        == repository.latest_version_href
    )

    # optimize=False forces a full pass even with no upstream change.
    third = sync(nuget_repo, remote, optimize=False)
    assert "sync.was_skipped" not in {report.code for report in third.progress_reports}

    # Changing the remote's filters invalidates the optimization.
    monitor_task(
        nuget_bindings.RemotesNugetApi.partial_update(
            remote.pulp_href, {"includes": ["Newtonsoft.Json.Bson [1.0.1, 1.0.3]"]}
        ).task
    )
    fourth = sync(nuget_repo, remote)
    assert "sync.was_skipped" not in {report.code for report in fourth.progress_reports}
    repository = nuget_bindings.RepositoriesNugetApi.read(nuget_repo.pulp_href)
    packages = nuget_bindings.ContentPackagesApi.list(
        repository_version=repository.latest_version_href, limit=100
    )
    versions = {package.version_normalized for package in packages.results}
    assert versions == {"1.0.1", "1.0.2", "1.0.3"}


def test_package_push(
    nuget_bindings,
    nuget_repo,
    nuget_distribution_factory,
    distribution_url_factory,
    newtonsoft_nupkg_path,
    bindings_cfg,
    monitor_task,
    anon_session,
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
        response = anon_session.put(publish_url, files={"package": fp})
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
    anon_session,
):
    """DELETE on the publish endpoint unlists a package; POST relists it."""
    newtonsoft_package_factory(repository=nuget_repo.pulp_href)
    distribution = nuget_distribution_factory(repository=nuget_repo.pulp_href)
    delete_url = f"{_publish_url(distribution, distribution_url_factory)}/Newtonsoft.Json/13.0.3"
    auth = (bindings_cfg.username, bindings_cfg.password)
    search_url = distribution_url_factory(distribution, "v3/search")

    assert anon_session.delete(delete_url).status_code == 401

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
    # Unique ids: content units outlive the test and a different file for a stored id
    # and version is rejected.
    suffix = uuid.uuid4().hex[:8]
    tool, lib, semver2 = (f"Pulp.Test.{name}.{suffix}" for name in ("Tool", "Lib", "Semver2"))
    for package_id, version, package_type in (
        (tool, "1.0.0", "DotnetTool"),
        (lib, "1.0.0", None),
        (semver2, "1.0.0-beta.1", None),
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

    assert ids() == {tool, lib}
    assert ids(packageType="DotnetTool") == {tool}
    # Matching is case-insensitive; no declared type means the implicit Dependency type.
    assert ids(packageType="dependency") == {lib}
    assert ids(packageType="NoSuchType") == set()
    # A dotted prerelease label is SemVer2: hidden unless semVerLevel=2.0.0.
    assert ids(prerelease="true") == {tool, lib}
    assert ids(prerelease="true", semVerLevel="2.0.0") == {tool, lib, semver2}

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


def test_sync_fails_when_no_included_package_exists(
    nuget_bindings,
    pulpcore_bindings,
    nuget_repo,
    newtonsoft_package_factory,
    remote_factory,
    monitor_task,
):
    """A sync whose allowlist matches nothing upstream fails instead of emptying a mirror."""
    newtonsoft_package_factory(repository=nuget_repo.pulp_href)
    before = nuget_bindings.RepositoriesNugetApi.read(nuget_repo.pulp_href).latest_version_href
    remote = remote_factory(includes=[f"Pulp.Nuget.No.Such.Package.{uuid.uuid4().hex}"])

    task_href = nuget_bindings.RepositoriesNugetApi.sync(
        nuget_repo.pulp_href, {"remote": remote.pulp_href, "mirror": True}
    ).task
    with pytest.raises(Exception):
        monitor_task(task_href)
    task = pulpcore_bindings.TasksApi.read(task_href)
    assert task.state == "failed"
    assert "includes" in task.error["description"]

    # The repository is untouched.
    repository = nuget_bindings.RepositoriesNugetApi.read(nuget_repo.pulp_href)
    assert repository.latest_version_href == before


def test_push_conflicting_package_is_rejected(
    nuget_repo,
    nuget_distribution_factory,
    distribution_url_factory,
    nupkg_factory,
    bindings_cfg,
    monitor_task,
):
    """Pushing a different file for an existing id and version is a 409, not a silent no-op."""
    distribution = nuget_distribution_factory(repository=nuget_repo.pulp_href)
    response = requests.get(distribution_url_factory(distribution, "v3/index.json"))
    response.raise_for_status()
    publish_url = next(
        resource["@id"]
        for resource in response.json()["resources"]
        if resource["@type"] == "PackagePublish/2.0.0"
    )
    auth = (bindings_cfg.username, bindings_cfg.password)

    def push(data):
        return requests.put(publish_url + "/", files={"package": ("p.nupkg", data)}, auth=auth)

    # Unique id: content units outlive the test and are deduplicated by id and version.
    package_id = f"Pulp.Push.{uuid.uuid4().hex[:8]}"
    with open(nupkg_factory(package_id, "1.0.0"), "rb") as fp:
        original = fp.read()
    with open(nupkg_factory(package_id, "1.0.0", readme=("README.md", b"changed")), "rb") as fp:
        changed = fp.read()
    assert original != changed

    response = push(original)
    assert response.status_code == 202, response.text
    monitor_task(response.json()["task"])

    # Pushing the identical file again stays idempotent.
    response = push(original)
    assert response.status_code == 202, response.text
    monitor_task(response.json()["task"])

    # A different file for the same id and version is refused, and the original stays.
    response = push(changed)
    assert response.status_code == 409, response.text
    nupkg_url = distribution_url_factory(
        distribution,
        f"v3-flatcontainer/{package_id.lower()}/1.0.0/{package_id.lower()}.1.0.0.nupkg",
    )
    assert requests.get(nupkg_url).content == original


def test_upload_conflicting_package_fails(
    nuget_bindings, pulpcore_bindings, nupkg_factory, package_upload_factory, monitor_task
):
    """Uploading a different file for an existing id and version fails instead of being dropped."""
    # Unique id: content units outlive the test and are deduplicated by id and version.
    package_id = f"Pulp.Upload.{uuid.uuid4().hex[:8]}"
    path = nupkg_factory(package_id, "1.0.0")
    package = package_upload_factory(path)

    # The identical file again returns the existing unit.
    assert package_upload_factory(path).pulp_href == package.pulp_href

    # nupkg_factory rewrites the same path with different content.
    changed = nupkg_factory(package_id, "1.0.0", readme=("README.md", b"changed"))
    task_href = nuget_bindings.ContentPackagesApi.create(file=changed).task
    with pytest.raises(Exception):
        monitor_task(task_href)
    task = pulpcore_bindings.TasksApi.read(task_href)
    assert task.state == "failed"
    assert "different file" in task.error["description"]
    assert nuget_bindings.ContentPackagesApi.read(package.pulp_href).sha256 == package.sha256
