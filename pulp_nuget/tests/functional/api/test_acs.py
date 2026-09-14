"""Functional tests for NuGet alternate content sources."""

import uuid

import pytest
from aiohttp import web


@pytest.fixture
def broken_feed(gen_threaded_aiohttp_server):
    """
    Serve a NuGet v3 feed whose metadata is valid but whose package downloads all 404.

    Returns a function registering a package version on the feed and the server data
    (``requests_record`` lists every requested path).
    """
    packages = {}
    record = []

    async def service_index(request):
        return web.json_response(
            {
                "version": "3.0.0",
                "resources": [
                    {
                        "@id": server.make_url("/registrations/"),
                        "@type": "RegistrationsBaseUrl/3.6.0",
                    }
                ],
            }
        )

    async def registration(request):
        package_id = request.match_info["package_id"]
        if package_id not in packages:
            raise web.HTTPNotFound()
        version = packages[package_id]
        leaf = {
            "catalogEntry": {"id": package_id, "version": version},
            "packageContent": server.make_url(f"/packages/{package_id}.{version}.nupkg"),
        }
        page = {"lower": version, "upper": version, "items": [leaf]}
        return web.json_response({"count": 1, "items": [page]})

    async def package(request):
        raise web.HTTPNotFound()

    @web.middleware
    async def recorder(request, handler):
        record.append(request.path)
        return await handler(request)

    app = web.Application(middlewares=[recorder])
    app.add_routes(
        [
            web.get("/v3/index.json", service_index),
            web.get("/registrations/{package_id}/index.json", registration),
            web.get("/packages/{name}", package),
        ]
    )
    server = gen_threaded_aiohttp_server(app, None, record)

    def _add_package(package_id, version):
        packages[package_id.lower()] = version

    return _add_package, server


def test_acs_validation(nuget_bindings, remote_factory):
    """ACS remotes must be on_demand with an allowlist, and paths must be relative."""
    immediate_remote = remote_factory(policy="immediate", includes=["Serilog"])
    with pytest.raises(nuget_bindings.module.ApiException) as exc:
        nuget_bindings.AcsNugetApi.create(
            {"name": str(uuid.uuid4()), "remote": immediate_remote.pulp_href}
        )
    assert exc.value.status == 400
    assert "on_demand" in exc.value.body

    no_includes_remote = remote_factory()
    with pytest.raises(nuget_bindings.module.ApiException) as exc:
        nuget_bindings.AcsNugetApi.create(
            {"name": str(uuid.uuid4()), "remote": no_includes_remote.pulp_href}
        )
    assert exc.value.status == 400
    assert "includes" in exc.value.body

    remote = remote_factory(includes=["Serilog"])
    with pytest.raises(nuget_bindings.module.ApiException) as exc:
        nuget_bindings.AcsNugetApi.create(
            {
                "name": str(uuid.uuid4()),
                "remote": remote.pulp_href,
                "paths": ["feed/v3/index.json", "/absolute/v3/index.json"],
            }
        )
    assert exc.value.status == 400
    assert "slash" in exc.value.body


def test_sync_downloads_from_acs(
    nuget_bindings,
    gen_object_with_cleanup,
    nupkg_factory,
    package_upload_factory,
    nuget_distribution_factory,
    remote_factory,
    sync,
    broken_feed,
    pulp_content_url,
    pulpcore_bindings,
    monitor_task,
    monitor_task_group,
):
    """An immediate sync whose remote cannot serve a package downloads it from an ACS."""
    add_package, feed = broken_feed
    package_id = f"Pulp.Acs.{uuid.uuid4().hex[:8]}"
    add_package(package_id, "1.0.0")

    repository = gen_object_with_cleanup(
        nuget_bindings.RepositoriesNugetApi, {"name": str(uuid.uuid4())}
    )
    remote = remote_factory(
        url=feed.make_url("/v3/index.json"), includes=[package_id], policy="immediate"
    )

    # Without an alternate content source, the package download fails.
    task_href = nuget_bindings.RepositoriesNugetApi.sync(
        repository.pulp_href, {"remote": remote.pulp_href}
    ).task
    with pytest.raises(Exception):
        monitor_task(task_href)
    assert pulpcore_bindings.TasksApi.read(task_href).state == "failed"
    assert f"/packages/{package_id.lower()}.1.0.0.nupkg" in feed.requests_record

    # Another Pulp feed has the same package: index it through an ACS path relative to
    # the content app root.
    source_repository = gen_object_with_cleanup(
        nuget_bindings.RepositoriesNugetApi, {"name": str(uuid.uuid4())}
    )
    package_upload_factory(
        nupkg_factory(package_id, "1.0.0"), repository=source_repository.pulp_href
    )
    source = nuget_distribution_factory(repository=source_repository.pulp_href)
    acs_remote = remote_factory(url=pulp_content_url, includes=[package_id], tls_validation=False)
    acs = gen_object_with_cleanup(
        nuget_bindings.AcsNugetApi,
        {
            "name": str(uuid.uuid4()),
            "remote": acs_remote.pulp_href,
            "paths": [f"{source.base_path}/v3/index.json"],
        },
    )
    task_group = monitor_task_group(nuget_bindings.AcsNugetApi.refresh(acs.pulp_href).task_group)
    assert task_group.completed == 1
    assert nuget_bindings.AcsNugetApi.read(acs.pulp_href).last_refreshed is not None

    feed.requests_record.clear()
    sync(repository, remote)

    repository = nuget_bindings.RepositoriesNugetApi.read(repository.pulp_href)
    packages = nuget_bindings.ContentPackagesApi.list(
        repository_version=repository.latest_version_href
    )
    assert [(p.package_id, p.version) for p in packages.results] == [(package_id, "1.0.0")]
    # The metadata still came from the remote, but the package came from the ACS.
    assert "/v3/index.json" in feed.requests_record
    assert not any(path.startswith("/packages/") for path in feed.requests_record)


def test_acs_rbac(nuget_bindings, gen_user, gen_object_with_cleanup, remote_factory):
    """Creating an ACS needs view on its remote; viewers can read an ACS but not refresh it."""
    remote = remote_factory(includes=["Serilog"])
    creator = gen_user(model_roles=["nuget.nugetalternatecontentsource_creator"])

    with creator, pytest.raises(nuget_bindings.module.ApiException) as exc:
        nuget_bindings.AcsNugetApi.create({"name": str(uuid.uuid4()), "remote": remote.pulp_href})
    assert exc.value.status == 403

    acs = gen_object_with_cleanup(
        nuget_bindings.AcsNugetApi, {"name": str(uuid.uuid4()), "remote": remote.pulp_href}
    )
    viewer = gen_user(object_roles=[("nuget.nugetalternatecontentsource_viewer", acs.pulp_href)])
    with viewer:
        assert nuget_bindings.AcsNugetApi.read(acs.pulp_href).name == acs.name
        with pytest.raises(nuget_bindings.module.ApiException) as exc:
            nuget_bindings.AcsNugetApi.refresh(acs.pulp_href)
    assert exc.value.status == 403
