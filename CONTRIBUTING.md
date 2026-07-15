# Contributing

Contributions are welcome via issues and pull requests on
[GitHub](https://github.com/PhillipDiCarlo/pulp_nuget).

`pulp_nuget` is a [Pulp 3](https://pulpproject.org/) plugin, so the general
[Pulp contributing docs](https://pulpproject.org/dev/) apply: the code layout,
testing approach, and changelog process all follow pulpcore's conventions.

## Development environment

The easiest way to run a Pulp instance with this plugin installed from source is
[oci-env](https://github.com/pulp/oci_env). Once it is running:

```bash
oci-env test -i -p pulp_nuget lint        # ruff + checks
oci-env test -i -p pulp_nuget unit        # unit tests
oci-env generate-client -i pulp_nuget     # bindings, needed once per API change
oci-env test -i -p pulp_nuget functional  # functional tests against the live instance
```

## Pull request checklist

- Add a changelog fragment in `CHANGES/` (towncrier format, e.g.
  `CHANGES/+fix-thing.bugfix` — see `CHANGES/.TEMPLATE.md` for the types).
- Add or extend tests: functional tests preferred for anything visible through the
  API or the NuGet protocol, unit tests for pure logic like nuspec parsing.
- Protocol behavior should match nuget.org's — when in doubt, diff the JSON our
  endpoints return against the equivalent resource from
  `https://api.nuget.org/v3/index.json`.

## Security issues

Please do not report security issues in public — follow the
[Pulp security disclosure procedure](https://docs.pulpproject.org/pulpcore/bugs-features.html#security-bugs).
