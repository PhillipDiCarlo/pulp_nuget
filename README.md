# pulp_nuget

A [Pulp 3](https://pulpproject.org/) plugin for hosting NuGet packages.

`pulp_nuget` serves a live **NuGet v3 API** that real clients (`dotnet`, `nuget.exe`)
can restore from, and can **sync/mirror** an allowlist of packages from any upstream
v3 feed (nuget.org or a private feed). v3 only — there is no v2/OData support.

## Features

- **Upload** `.nupkg` files; all metadata (id, version, authors, description, tags,
  license, dependency groups per target framework, minClientVersion) is parsed
  server-side from the embedded `.nuspec`.
- **Serve** a NuGet v3 API per distribution — service index, flat container
  (package downloads, `.nuspec` manifests, embedded icons and READMEs),
  registrations, and search — generated live from the repository's latest version.
  No publish step is needed.
  Registration indexes page externally past 64 versions (like nuget.org), and
  search honors the `packageType` and `semVerLevel` query parameters.
- **Sync** an allowlist of packages (`includes`) from an upstream v3 service
  index, with `immediate` or `on_demand` download policy. On-demand packages are
  fetched from the upstream and cached on first client request. Entries take
  optional NuGet version ranges (`"Serilog [2.0,3.0)"`), an `excludes` list filters
  further, and unchanged repeat syncs are skipped automatically.
- **Push** packages with `dotnet nuget push`: each distribution advertises a
  `PackagePublish/2.0.0` resource that adds pushed packages to its repository.
  Pushing requires the `nuget.publish_nugetdistribution` permission (grant the
  `nuget.nugetdistribution_publisher` role); configure source credentials in
  `nuget.config`.
- **Unlist** packages with `dotnet nuget delete` (nuget.org semantics: hidden from
  search but still restorable by exact version); relist with a POST to the same URL.
- **Symbol packages**: push `.snupkg` files via the `SymbolPackagePublish/4.9.0`
  resource, and each distribution doubles as an SSQP **symbol server** — point
  Visual Studio or `dotnet-symbol` at `<distribution>/symbols/` to fetch the
  portable PDBs.
- **Retention**: set `retain_package_versions` on a repository to keep only the
  newest N versions of each package id in new repository versions, whatever the
  content path (sync, push, upload, modify).
- **Import/export**: move repositories to air-gapped instances with pulpcore's
  PulpExporter/PulpImporter; packages and symbol packages round-trip with all
  parsed metadata.
- **Private feeds**: protect a distribution with a `NugetContentGuard`. It grants
  access by RBAC role (`nuget.nugetcontentguard_downloader`) and challenges anonymous
  requests with `401 WWW-Authenticate: Basic` — which real NuGet clients require
  before they send credentials (the stock RBAC guard's plain 403 does not work).
- **RBAC** throughout: creator/owner/viewer roles on repositories, remotes,
  distributions, and content guards; queryset scoping hides objects users cannot view.
- Content is identified by the natural key *(lowercase package id, lowercase
  NuGet-normalized SemVer2 version)*, so re-uploads and syncs deduplicate cleanly.
- Works with Pulp **domains** enabled (multi-tenancy): all endpoints, including
  push/unlist, operate in the distribution's domain.

## Quickstart

Create a repository, upload a package, and distribute it:

```bash
http --auth admin:password POST :5001/pulp/api/v3/repositories/nuget/nuget/ name=foo
http --auth admin:password -f POST :5001/pulp/api/v3/content/nuget/packages/ \
    file@newtonsoft.json.13.0.3.nupkg repository=<repo_href>
http --auth admin:password POST :5001/pulp/api/v3/distributions/nuget/nuget/ \
    name=foo base_path=foo repository=<repo_href>
```

Point a NuGet client at the distribution's service index:

```bash
dotnet nuget add source http://<host>:<port>/pulp/content/foo/v3/index.json --name pulp
dotnet add package Newtonsoft.Json
```

(For plain-http Pulp instances, the source needs `allowInsecureConnections="true"`
in `nuget.config` with newer .NET SDKs.)

Push a package (the source must be repository-backed and credentials configured):

```bash
dotnet nuget push my.package.1.0.0.nupkg --source pulp --api-key unused
```

The `X-NuGet-ApiKey` header is deliberately ignored — authentication is HTTP basic via
`packageSourceCredentials`, so pass any value for `--api-key`. Unlist and relist:

```bash
dotnet nuget delete My.Package 1.0.0 --source pulp --api-key unused --non-interactive
http --auth admin:password POST :5001/pulp_nuget/publish/foo/My.Package/1.0.0
```

Or mirror packages from nuget.org:

```bash
http --auth admin:password POST :5001/pulp/api/v3/remotes/nuget/nuget/ \
    name=nugetorg url=https://api.nuget.org/v3/index.json policy=on_demand \
    includes:='["Newtonsoft.Json"]'
http --auth admin:password POST :5001<repo_href>sync/ remote=<remote_href>
```

## Private feeds

```bash
http --auth admin:password POST :5001/pulp/api/v3/contentguards/nuget/nuget/ name=private
http --auth admin:password PATCH :5001<distribution_href> content_guard=<guard_href>
http --auth admin:password POST :5001<guard_href>add_role/ \
    role=nuget.nugetcontentguard_downloader users:='["alice"]'
```

Clients keep working unchanged: the guard 401-challenges them, and they retry with the
`packageSourceCredentials` from `nuget.config`.

## Troubleshooting restores

When a client fails to restore, diff the resource it requested against the equivalent
resource from `https://api.nuget.org/v3/index.json` — the JSON shapes are modeled on
nuget.org's responses.

How to File an Issue
--------------------

File through this project's GitHub issues and appropriate labels.

> **WARNING** Is this security related? If so, please follow the [Security Disclosures](https://docs.pulpproject.org/pulpcore/bugs-features.html#security-bugs) procedure.
