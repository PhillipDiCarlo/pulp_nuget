Added replication support: a downstream Pulp's ``UpstreamPulp`` replicate task now
mirrors the upstream's nuget distributions, maintaining a remote, a mirror-synced
repository, and a distribution for each. This builds on the new ``includes=["*"]``
wildcard, which syncs every package the upstream's search service enumerates.
