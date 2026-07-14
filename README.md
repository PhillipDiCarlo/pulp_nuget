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
  (package downloads), registrations, and search — generated live from the
  repository's latest version. No publish step is needed.
- **Sync** an allowlist of package ids (`includes`) from an upstream v3 service
  index, with `immediate` or `on_demand` download policy. On-demand packages are
  fetched from the upstream and cached on first client request.
- Content is identified by the natural key *(lowercase package id, lowercase
  NuGet-normalized SemVer2 version)*, so re-uploads and syncs deduplicate cleanly.

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

Or mirror packages from nuget.org:

```bash
http --auth admin:password POST :5001/pulp/api/v3/remotes/nuget/nuget/ \
    name=nugetorg url=https://api.nuget.org/v3/index.json policy=on_demand \
    includes:='["Newtonsoft.Json"]'
http --auth admin:password POST :5001<repo_href>sync/ remote=<remote_href>
```

## Troubleshooting restores

When a client fails to restore, diff the resource it requested against the equivalent
resource from `https://api.nuget.org/v3/index.json` — the JSON shapes are modeled on
nuget.org's responses.

How to File an Issue
--------------------

File through this project's GitHub issues and appropriate labels.

> **WARNING** Is this security related? If so, please follow the [Security Disclosures](https://docs.pulpproject.org/pulpcore/bugs-features.html#security-bugs) procedure.
