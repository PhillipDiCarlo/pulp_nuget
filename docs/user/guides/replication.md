# Replicate Another Pulp Instance

A downstream Pulp can mirror all nuget distributions of an upstream Pulp
automatically. Point an `UpstreamPulp` at the other instance and run replicate:

```bash
http --auth admin:password POST :5001/pulp/api/v3/upstream-pulps/ \
    name=upstream base_url=https://upstream.example.com api_root=/pulp/ \
    username=replicator password=s3cret
http --auth admin:password POST :5001<upstream_pulp_href>replicate/
```

For every nuget distribution on the upstream, replication maintains on the
downstream: a remote pointed at that distribution's service index (with the `*`
wildcard allowlist), a repository synced from it in **mirror** mode, and a
distribution serving it under the same `base_path`. Re-running replicate picks up
upstream changes; distributions that disappeared upstream are removed (tune this
with the `UpstreamPulp.policy` field, e.g. `nodelete`). Use `q_select` (e.g.
`name="feed"` or a label filter) to replicate only a subset of distributions.

## The `*` wildcard

Replication relies on wildcard syncing, which is also usable directly: a remote
with `includes=["*"]` mirrors every package the upstream's **search service**
enumerates. This is intended for Pulp-to-Pulp mirroring and other small feeds — do
not point it at nuget.org. Packages whose versions are all unlisted are invisible
to search and are skipped; `excludes` entries still apply on top of the wildcard.
