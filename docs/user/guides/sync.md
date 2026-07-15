# Mirror an Upstream Feed

Sync an allowlist of package ids from any NuGet v3 feed (nuget.org or a private feed).

## Create a remote

The remote's `url` is the upstream **service index**; `includes` is the list of package
ids to mirror (all versions of each id are synced):

```bash
http --auth admin:password POST :5001/pulp/api/v3/remotes/nuget/nuget/ \
    name=nugetorg url=https://api.nuget.org/v3/index.json policy=on_demand \
    includes:='["Newtonsoft.Json", "Serilog"]'
```

With `policy=on_demand`, only metadata is synced; package binaries are fetched from
the upstream and cached the first time a client requests them. Use `policy=immediate`
to download everything up front.

## Sync

```bash
http --auth admin:password POST :5001<repo_href>sync/ remote=<remote_href>
```

The sync honors the upstream's `listed` flags, so versions unlisted on the upstream
stay hidden from search in your mirror too.
