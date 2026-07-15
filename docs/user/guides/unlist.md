# Unlist and Relist Versions

`pulp_nuget` implements nuget.org's unlisting semantics: an unlisted version is hidden
from search and marked `listed: false` in registrations, but remains restorable by
exact version so existing lock files keep working.

## Unlist

```bash
dotnet nuget delete My.Package 1.0.0 --source pulp --api-key unused --non-interactive
```

## Relist

POST to the same publish URL:

```bash
http --auth admin:password POST :5001/pulp_nuget/publish/<base_path>/My.Package/1.0.0
```

Both operations require the `nuget.publish_nugetdistribution` permission on the
distribution, like [pushing](push.md).

!!! warning

    The `listed` flag lives on the content unit itself, so unlisting a version affects
    every repository and distribution that serves that same package version.
