# Private Feeds

Protect a distribution with a `NugetContentGuard` so only authorized users can restore
from it.

## Why a NuGet-specific guard?

NuGet clients only send the credentials configured in `nuget.config` after receiving a
`401` response with a `WWW-Authenticate: Basic` challenge. Pulpcore's stock RBAC
content guard denies anonymous requests with a plain `403`, which real clients never
retry with credentials — restores fail with `NU1301`. The `NugetContentGuard` issues
the proper challenge, then authorizes by RBAC role exactly like the stock guard.

## Set it up

```bash
http --auth admin:password POST :5001/pulp/api/v3/contentguards/nuget/nuget/ name=private
http --auth admin:password PATCH :5001<distribution_href> content_guard=<guard_href>
http --auth admin:password POST :5001<guard_href>add_role/ \
    role=nuget.nugetcontentguard_downloader users:='["alice"]'
```

Clients keep working unchanged: the guard 401-challenges them, and they retry with the
`packageSourceCredentials` from `nuget.config`:

```bash
dotnet nuget add source http://<host>:<port>/pulp/content/foo/v3/index.json \
    --name pulp --username alice --password s3cret --store-password-in-clear-text
dotnet restore
```

Users without the role receive a `403` even with valid credentials.

!!! warning "Known issue with `CACHE_ENABLED`"

    If your Pulp instance runs with content caching enabled, anonymous requests to a
    `NugetContentGuard`-protected distribution get a `500` instead of the intended
    `401` challenge. This is a bug in pulpcore's content-cache authentication wrapper
    (`Handler.auth_cached`): it only handles content guards that raise
    `HTTPForbidden`, but our guard deliberately raises `HTTPUnauthorized` — which
    pulpcore's own `Handler._permit` documents as a supported pattern for content
    guards. Until that's fixed upstream, run with `CACHE_ENABLED = False` if you use
    this guard.
