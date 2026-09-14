# Download from Alternate Content Sources

An alternate content source (ACS) is another feed that has copies of packages you
sync, typically one that is closer or cheaper to reach than the remote: a mirror in
your own network, or another Pulp instance. A sync still reads package metadata from
its remote, but downloads each package from an ACS that has it and only falls back
to the remote when no ACS copy can be fetched.

## Create and refresh an ACS

An ACS uses an `on_demand` remote whose `includes` allowlist names the packages to
index (`*` indexes everything the feed's search service enumerates, which suits
another Pulp instance):

```bash
http --auth admin:password POST :5001/pulp/api/v3/remotes/nuget/nuget/ \
    name=mirror url=https://mirror.example.com/v3/index.json \
    policy=on_demand includes:='["*"]'
http --auth admin:password POST :5001/pulp/api/v3/acs/nuget/nuget/ \
    name=mirror remote=<remote_href>
http --auth admin:password POST :5001<acs_href>refresh/
```

Refreshing indexes the feed's packages without downloading them, and returns a task
group. Refresh again whenever the feed gains packages you want served from it; an
unchanged feed is skipped quickly.

To index several feeds on the same server with one ACS, give the remote the server's
base URL and list each service index as a path relative to it:

```bash
http --auth admin:password POST :5001/pulp/api/v3/remotes/nuget/nuget/ \
    name=pulp-mirror url=https://pulp.example.com/pulp/content/ \
    policy=on_demand includes:='["*"]'
http --auth admin:password POST :5001/pulp/api/v3/acs/nuget/nuget/ \
    name=pulp-mirror remote=<remote_href> \
    paths:='["team-a/v3/index.json", "team-b/v3/index.json"]'
```

## How packages are matched

NuGet feeds publish no checksums before a package is downloaded, so an ACS copy is
matched by **package id and version**. This relies on NuGet's rule that a published
package id and version can never be replaced with different contents; only add
alternate sources you trust to hold the same packages as your remotes.

- **`immediate` syncs** download each package from the first ACS copy that succeeds,
  using that ACS remote's own credentials, proxy, and TLS settings, and fall back to
  the sync's remote.
- **`on_demand` content** is streamed from an ACS copy first when a client requests
  it, falling back to the remote that synced it.

ACSes apply to every sync in their domain. Deleting an ACS removes its index; syncs
then download from their remotes again.
