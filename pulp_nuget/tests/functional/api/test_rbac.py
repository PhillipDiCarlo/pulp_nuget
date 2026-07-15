"""Functional tests for RBAC: viewset access policies, the push permission, content guards."""

import uuid

import pytest
import requests


@pytest.fixture
def publish_url_factory(distribution_url_factory):
    def _publish_url(distribution):
        response = requests.get(distribution_url_factory(distribution, "v3/index.json"))
        response.raise_for_status()
        return next(
            resource["@id"]
            for resource in response.json()["resources"]
            if resource["@type"] == "PackagePublish/2.0.0"
        )

    return _publish_url


def test_rbac_repository_crud(nuget_bindings, gen_user, gen_object_with_cleanup, monitor_task):
    """Repository creation needs nuget.add_nugetrepository; creators own what they create."""
    nobody = gen_user()
    creator = gen_user(model_roles=["nuget.nugetrepository_creator"])

    with nobody, pytest.raises(nuget_bindings.module.ApiException) as exc:
        nuget_bindings.RepositoriesNugetApi.create({"name": str(uuid.uuid4())})
    assert exc.value.status == 403

    with creator:
        repository = gen_object_with_cleanup(
            nuget_bindings.RepositoriesNugetApi, {"name": str(uuid.uuid4())}
        )
        # The creation hook grants the owner role: the creator can read their repository.
        assert nuget_bindings.RepositoriesNugetApi.read(repository.pulp_href)

    # Queryset scoping hides the repository from users without view permission.
    with nobody:
        names = {
            result.name for result in nuget_bindings.RepositoriesNugetApi.list(limit=1000).results
        }
    assert repository.name not in names


def test_rbac_content_upload_requires_repository_perms(
    nuget_bindings, nuget_repo, gen_user, newtonsoft_nupkg_path
):
    """Non-admin uploads must target a repository the user may modify."""
    nobody = gen_user()

    # No repository parameter: rejected for non-admins (pulpcore reports this as a 400).
    with nobody, pytest.raises(nuget_bindings.module.ApiException) as exc:
        nuget_bindings.ContentPackagesApi.create(file=newtonsoft_nupkg_path)
    assert exc.value.status in (400, 403)

    # An admin-owned repository the user has no permissions on: denied too.
    with nobody, pytest.raises(nuget_bindings.module.ApiException) as exc:
        nuget_bindings.ContentPackagesApi.create(
            file=newtonsoft_nupkg_path, repository=nuget_repo.pulp_href
        )
    assert exc.value.status == 403


def test_rbac_push_permission(
    nuget_repo,
    newtonsoft_package_factory,
    nuget_distribution_factory,
    publish_url_factory,
    newtonsoft_nupkg_path,
    gen_user,
):
    """Push, unlist, and relist require nuget.publish_nugetdistribution."""
    newtonsoft_package_factory(repository=nuget_repo.pulp_href)
    distribution = nuget_distribution_factory(repository=nuget_repo.pulp_href)
    publish_url = publish_url_factory(distribution)
    delete_url = f"{publish_url}/Newtonsoft.Json/13.0.3"

    nobody = gen_user()
    publisher = gen_user(
        object_roles=[("nuget.nugetdistribution_publisher", distribution.pulp_href)]
    )
    nobody_auth = (nobody.username, nobody.password)
    publisher_auth = (publisher.username, publisher.password)

    # An authenticated user without the permission is rejected everywhere.
    with open(newtonsoft_nupkg_path, "rb") as fp:
        response = requests.put(publish_url + "/", files={"package": fp}, auth=nobody_auth)
    assert response.status_code == 403
    assert requests.delete(delete_url, auth=nobody_auth).status_code == 403
    assert requests.post(delete_url, auth=nobody_auth).status_code == 403

    # The object-level publisher role allows the whole push surface...
    with open(newtonsoft_nupkg_path, "rb") as fp:
        response = requests.put(publish_url + "/", files={"package": fp}, auth=publisher_auth)
    assert response.status_code == 202, response.text
    try:
        assert requests.delete(delete_url, auth=publisher_auth).status_code == 204
    finally:
        assert requests.post(delete_url, auth=publisher_auth).status_code == 200

    # ...but grants nothing else, e.g. repository creation stays denied.
    other = nuget_distribution_factory(repository=nuget_repo.pulp_href)
    other_url = publish_url_factory(other)
    with open(newtonsoft_nupkg_path, "rb") as fp:
        response = requests.put(other_url + "/", files={"package": fp}, auth=publisher_auth)
    assert response.status_code == 403


def test_nuget_content_guard_basic_challenge(
    nuget_bindings,
    nuget_repo,
    newtonsoft_package_factory,
    nuget_distribution_factory,
    distribution_url_factory,
    gen_user,
    gen_object_with_cleanup,
):
    """The nuget content guard 401-challenges anonymous clients and honors the download role."""
    newtonsoft_package_factory(repository=nuget_repo.pulp_href)
    guard = gen_object_with_cleanup(
        nuget_bindings.ContentguardsNugetApi, {"name": str(uuid.uuid4())}
    )
    distribution = nuget_distribution_factory(
        repository=nuget_repo.pulp_href, content_guard=guard.pulp_href
    )
    index_url = distribution_url_factory(distribution, "v3/index.json")
    nupkg_url = distribution_url_factory(
        distribution, "v3-flatcontainer/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg"
    )

    # Anonymous requests get the Basic challenge NuGet clients require to send credentials.
    response = requests.get(index_url)
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate", "").startswith("Basic")

    # Authenticated users without the download permission are refused.
    outsider = gen_user()
    response = requests.get(index_url, auth=(outsider.username, outsider.password))
    assert response.status_code == 403

    # The object-level downloader role unlocks the whole feed.
    reader = gen_user(object_roles=[("nuget.nugetcontentguard_downloader", guard.pulp_href)])
    for url in (index_url, nupkg_url):
        response = requests.get(url, auth=(reader.username, reader.password))
        assert response.status_code == 200, url


def test_rbac_content_guard(
    pulpcore_bindings,
    nuget_repo,
    newtonsoft_package_factory,
    nuget_distribution_factory,
    distribution_url_factory,
    gen_user,
    gen_object_with_cleanup,
    bindings_cfg,
):
    """An RBAC content guard restricts the whole v3 API to users with the download role."""
    newtonsoft_package_factory(repository=nuget_repo.pulp_href)
    guard = gen_object_with_cleanup(
        pulpcore_bindings.ContentguardsRbacApi, {"name": str(uuid.uuid4())}
    )
    distribution = nuget_distribution_factory(
        repository=nuget_repo.pulp_href, content_guard=guard.pulp_href
    )
    index_url = distribution_url_factory(distribution, "v3/index.json")
    nupkg_url = distribution_url_factory(
        distribution, "v3-flatcontainer/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg"
    )

    reader = gen_user()
    outsider = gen_user()
    pulpcore_bindings.ContentguardsRbacApi.add_role(
        guard.pulp_href,
        {"users": [reader.username], "role": "core.rbaccontentguard_downloader"},
    )

    assert requests.get(index_url).status_code == 403
    assert requests.get(index_url, auth=(outsider.username, outsider.password)).status_code == 403
    for url in (index_url, nupkg_url):
        response = requests.get(url, auth=(reader.username, reader.password))
        assert response.status_code == 200, url
    # Admin passes any guard.
    admin_auth = (bindings_cfg.username, bindings_cfg.password)
    assert requests.get(index_url, auth=admin_auth).status_code == 200
