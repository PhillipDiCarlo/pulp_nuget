# About NuGet Repositories

The `pulp_nuget` plugin extends [pulpcore](site:pulpcore/) to host NuGet packages.

## Overview

A `pulp_nuget` repository holds `.nupkg` packages. Each distribution serves a live
**NuGet v3 API** — service index, flat container, registrations, and search — generated
from the repository's latest version, so there is no publish step. Real clients
(`dotnet`, `nuget.exe`, Visual Studio) can restore from it, push to it with
`dotnet nuget push`, and unlist versions with `dotnet nuget delete`.

Repositories can also **sync** an allowlist of package ids from any upstream NuGet v3
feed (such as nuget.org), either downloading everything immediately or fetching
packages on demand as clients first request them.

Only the v3 protocol is implemented; there is no v2/OData support.

## Get started

- [Upload and host packages](site:pulp_nuget/docs/user/guides/upload-host/)
- [Mirror packages from an upstream feed](site:pulp_nuget/docs/user/guides/sync/)
- [Push packages with the dotnet CLI](site:pulp_nuget/docs/user/guides/push/)
- [Protect a feed with authentication](site:pulp_nuget/docs/admin/guides/private-feeds/)
