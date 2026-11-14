# Mirror an Upstream Feed

Sync an allowlist of package ids from any NuGet v3 feed (nuget.org or a private feed).

## Create a remote

The remote's `url` is the upstream **service index**; `includes` is the list of
packages to mirror:

```bash
http --auth admin:password POST :5001/pulp/api/v3/remotes/nuget/nuget/ \
    name=nugetorg url=https://api.nuget.org/v3/index.json policy=on_demand \
    includes:='["Newtonsoft.Json", "Serilog"]'
```

With `policy=on_demand`, only metadata is synced; package binaries are fetched from
the upstream and cached the first time a client requests them. Use `policy=immediate`
to download everything up front.

## Filter versions

An `includes` entry is a package id, optionally followed by a NuGet version range;
`excludes` uses the same syntax and is applied afterwards:

```bash
http --auth admin:password POST :5001/pulp/api/v3/remotes/nuget/nuget/ \
    name=serilog4 url=https://api.nuget.org/v3/index.json policy=on_demand \
    includes:='["Serilog [4.0.0,)"]' excludes:='["Serilog [4.2.0]"]'
```

Supported range forms: `2.0` (that version or higher), `[2.0]` (exactly that
version), and intervals like `[2.0,3.0)`, `(2.0,)`, or `(,3.0]`.

An include range only matches **prerelease** versions when one of its bounds carries
a prerelease label (`[4.0.0-alpha,)` opts them in), mirroring NuGet's own convention.
Exclude ranges match by pure precedence, so excluding `(,2.0)` also drops 2.0's
prereleases. A plain id with no range syncs everything, prereleases included.

## Sync

```bash
http --auth admin:password POST :5001<repo_href>sync/ remote=<remote_href>
```

The sync honors the upstream's `listed` flags, so versions unlisted on the upstream
stay hidden from search in your mirror too. Passing `mirror=true` makes the
repository version an exact mirror of the filtered selection, removing anything else.

A package id in `includes` that the upstream does not have is skipped, with a warning
in the Pulp worker log. If none of them exist, the sync fails instead, so a typo or a
wrong `url` cannot turn a `mirror=true` sync into an empty repository.

A published package version cannot be replaced. If the upstream serves a different file
for a package id and version that Pulp already stores (uploaded, pushed, or synced from
another feed), the sync fails and names the package; add it to `excludes`, or remove the
stored package from every repository and run orphan cleanup, then sync again.

An `on_demand` sync makes the same comparison, once: the first time a remote offers a
version that Pulp already stores, the sync downloads that one file. Later syncs from that
remote do not download it again, and versions with no stored file are not downloaded at
all. So if two `on_demand` remotes offer different files for a version that is not stored
yet, the one a client requests first is stored and served from then on.

## Repeated syncs are cheap

The sync is skipped entirely when nothing changed: the remote's configuration, the
repository's `retain_package_versions`, and the checksums of the upstream registration
indexes are recorded on the repository (`last_sync_details`), and a resync with the
same state short-circuits with a `sync.was_skipped` progress report. Pass `optimize=false` to force a full pass.

Version-range filters also avoid downloading registration pages whose version window
can't match — syncing `Serilog [4.0.0,)` fetches a couple of pages, not all ~600
versions' worth.

## Keep only recent versions

Set `retain_package_versions` on the repository to cap how many versions of each
package id a repository version holds:

```bash
http --auth admin:password PATCH :5001<repo_href> retain_package_versions:=3
```

Every new repository version then keeps only the newest N versions per package id
(by NuGet precedence — a prerelease ranks just below its release) and drops the
rest, no matter how the content arrived: sync, `dotnet nuget push`, upload, or
modify. A symbol package is kept or dropped together with its package version. The
default `0` keeps everything. Changing the setting does not rewrite existing repository
versions; it applies from the next content change onward.

Whenever a new repository version drops content this way, its task carries a
`retention.trimmed` progress report with the number of units removed. That includes a
version you just added, if it is older than the retained ones: the task succeeds, but
the version does not appear in the repository.
