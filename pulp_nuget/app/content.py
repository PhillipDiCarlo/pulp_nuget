"""
Extra content-app routes for pulp_nuget.

Most of the NuGet v3 API is served through NugetDistribution.content_handler, but the
SearchQueryService needs access to query parameters (q, skip, take, prerelease), which
content_handler does not receive — so search is registered as an explicit route here.
This module is auto-imported by the pulpcore content app on startup.
"""

from aiohttp import web
from asgiref.sync import sync_to_async
from django.conf import settings

from pulpcore.plugin.content import app

from pulp_nuget.app import v3_api
from pulp_nuget.app.models import NugetDistribution


def _int_param(request, name, default):
    try:
        return max(0, int(request.query.get(name, default)))
    except ValueError:
        return default


def _search_blocking(path, query, skip, take, prerelease, package_type, sem_ver_level):
    kwargs = {"base_path": path}
    if settings.DOMAIN_ENABLED:
        domain_name, _, base_path = path.partition("/")
        kwargs = {"pulp_domain__name": domain_name, "base_path": base_path}
    try:
        distribution = NugetDistribution.objects.get(**kwargs)
    except NugetDistribution.DoesNotExist:
        return None
    return v3_api.search(
        distribution,
        query=query,
        skip=skip,
        take=take,
        prerelease=prerelease,
        package_type=package_type,
        sem_ver_level=sem_ver_level,
    )


async def search(request):
    """Serve <distribution base url>/v3/search."""
    data = await sync_to_async(_search_blocking)(
        request.match_info["path"],
        request.query.get("q", ""),
        _int_param(request, "skip", 0),
        _int_param(request, "take", 20),
        request.query.get("prerelease", "false").lower() == "true",
        request.query.get("packageType", ""),
        request.query.get("semVerLevel", ""),
    )
    if data is None:
        raise web.HTTPNotFound()
    return web.json_response(data)


app.add_routes([web.get(settings.CONTENT_PATH_PREFIX + "{path:.+}/v3/search", search)])
