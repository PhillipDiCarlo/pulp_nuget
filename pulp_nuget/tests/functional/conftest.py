import os
import uuid

import pytest

from pulpcore.tests.functional.utils import BindingsNamespace

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
NEWTONSOFT_NUPKG = os.path.join(ASSETS_DIR, "newtonsoft.json.13.0.3.nupkg")


@pytest.fixture(scope="session")
def nuget_bindings(_api_client_set, bindings_cfg):
    """
    A namespace providing preconfigured pulp_nuget api clients.

    e.g. `nuget_bindings.RepositoriesNugetApi.list()`.
    """
    from pulpcore.client import pulp_nuget as nuget_bindings_module

    api_client = nuget_bindings_module.ApiClient(bindings_cfg)
    _api_client_set.add(api_client)
    yield BindingsNamespace(nuget_bindings_module, api_client)
    _api_client_set.remove(api_client)


@pytest.fixture
def nuget_repo(nuget_bindings, gen_object_with_cleanup):
    return gen_object_with_cleanup(nuget_bindings.RepositoriesNugetApi, {"name": str(uuid.uuid4())})


@pytest.fixture
def nuget_distribution_factory(nuget_bindings, gen_object_with_cleanup):
    def _nuget_distribution_factory(**body):
        data = {"base_path": str(uuid.uuid4()), "name": str(uuid.uuid4())}
        data.update(body)
        return gen_object_with_cleanup(nuget_bindings.DistributionsNugetApi, data)

    return _nuget_distribution_factory


@pytest.fixture
def newtonsoft_nupkg_path():
    """Filesystem path of the Newtonsoft.Json fixture package."""
    return NEWTONSOFT_NUPKG


@pytest.fixture
def newtonsoft_package_factory(nuget_bindings, monitor_task):
    """Upload the Newtonsoft.Json fixture .nupkg, optionally into a repository."""

    def _newtonsoft_package_factory(**kwargs):
        response = nuget_bindings.ContentPackagesApi.create(file=NEWTONSOFT_NUPKG, **kwargs)
        task = monitor_task(response.task)
        package_href = next(
            resource for resource in task.created_resources if "content/nuget/packages/" in resource
        )
        return nuget_bindings.ContentPackagesApi.read(package_href)

    return _newtonsoft_package_factory
