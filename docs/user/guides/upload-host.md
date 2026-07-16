# Upload and Host Packages

Create a repository, upload a `.nupkg`, and serve it to NuGet clients.

## Create a repository and upload a package

```bash
http --auth admin:password POST :5001/pulp/api/v3/repositories/nuget/nuget/ name=foo
http --auth admin:password -f POST :5001/pulp/api/v3/content/nuget/packages/ \
    file@newtonsoft.json.13.0.3.nupkg repository=<repo_href>
```

All metadata (id, version, authors, description, tags, license, dependency groups per
target framework, package types, minClientVersion) is parsed server-side from the
`.nuspec` embedded in the package — nothing else needs to be supplied.

Packages that embed an icon or README (the `<icon>`/`<readme>` nuspec elements) get
them served at `v3-flatcontainer/{id}/{version}/icon` and `.../readme`, like on
nuget.org; search results and registrations point `iconUrl` at the icon endpoint.

Content is identified by the natural key *(lowercase package id, lowercase
NuGet-normalized SemVer2 version)*, so re-uploading the same package deduplicates
cleanly.

## Distribute it

```bash
http --auth admin:password POST :5001/pulp/api/v3/distributions/nuget/nuget/ \
    name=foo base_path=foo repository=<repo_href>
```

The distribution serves a full NuGet v3 API from the repository's **latest** version.
No publication step is needed; adding or removing content is visible immediately.

## Restore from it

Point a client at the distribution's service index:

```bash
dotnet nuget add source http://<host>:<port>/pulp/content/foo/v3/index.json --name pulp
dotnet add package Newtonsoft.Json
```

!!! note

    For plain-http Pulp instances, newer .NET SDKs require
    `allowInsecureConnections="true"` on the source in `nuget.config`.
