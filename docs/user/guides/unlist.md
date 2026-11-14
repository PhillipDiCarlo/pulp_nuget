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

Both operations require the same permissions as [pushing](push.md):
`nuget.publish_nugetdistribution` on the distribution and `nuget.modify_nugetrepository`
on its repository.

!!! warning

    The `listed` flag lives on the content unit itself, so unlisting a version affects
    every repository and distribution in the domain that serves that same package
    version, including earlier repository versions. A sync does not change the flag of a
    version that is already stored.
