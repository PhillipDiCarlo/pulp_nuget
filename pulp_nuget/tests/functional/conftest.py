import os
import uuid
import zipfile

import pytest
import requests

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
def remote_factory(nuget_bindings, gen_object_with_cleanup):
    """Create a NugetRemote pointed at nuget.org (override any field via kwargs)."""

    def _remote_factory(**body):
        data = {
            "name": str(uuid.uuid4()),
            "url": "https://api.nuget.org/v3/index.json",
            "policy": "on_demand",
        }
        data.update(body)
        return gen_object_with_cleanup(nuget_bindings.RemotesNugetApi, data)

    return _remote_factory


@pytest.fixture
def sync(nuget_bindings, monitor_task):
    """Run a sync to completion and return the finished task (with progress reports)."""

    def _sync(repository, remote, **body):
        data = {"remote": remote.pulp_href, **body}
        response = nuget_bindings.RepositoriesNugetApi.sync(repository.pulp_href, data)
        return monitor_task(response.task)

    return _sync


@pytest.fixture
def anon_session():
    """
    A requests session that ignores ~/.netrc.

    CI writes admin credentials to .netrc for the pulp host so pulp-cli and the
    bindings can authenticate without extra config; plain ``requests`` calls pick
    those up too unless trust_env is disabled, silently defeating anonymous-access
    checks.
    """
    session = requests.Session()
    session.trust_env = False
    return session


@pytest.fixture
def distribution_url_factory(pulp_content_url):
    """Build an absolute URL under a distribution's base path."""

    def _distribution_url(distribution, path):
        return f"{pulp_content_url}{distribution.base_path}/{path}"

    return _distribution_url


@pytest.fixture
def nupkg_factory(tmp_path):
    """Build a minimal synthetic .nupkg on disk and return its path."""

    def _nupkg_factory(package_id, version, package_type=None):
        package_types = ""
        if package_type:
            package_types = f'<packageTypes><packageType name="{package_type}" /></packageTypes>'
        nuspec = f"""<?xml version="1.0"?>
        <package xmlns="http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd">
          <metadata>
            <id>{package_id}</id>
            <version>{version}</version>
            <authors>pulp_nuget tests</authors>
            <description>A synthetic test package.</description>
            {package_types}
          </metadata>
        </package>"""
        path = tmp_path / f"{package_id}.{version}.nupkg"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"{package_id}.nuspec", nuspec)
        return str(path)

    return _nupkg_factory


@pytest.fixture
def package_upload_factory(nuget_bindings, monitor_task):
    """Upload a .nupkg by path, optionally into a repository, and return the content unit."""

    def _package_upload_factory(path, **kwargs):
        response = nuget_bindings.ContentPackagesApi.create(file=path, **kwargs)
        task = monitor_task(response.task)
        package_href = next(
            resource for resource in task.created_resources if "content/nuget/packages/" in resource
        )
        return nuget_bindings.ContentPackagesApi.read(package_href)

    return _package_upload_factory


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
