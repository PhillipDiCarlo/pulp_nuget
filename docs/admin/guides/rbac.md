# Role-Based Access Control

`pulp_nuget` ships RBAC access policies on all of its endpoints, following the same
model as pulpcore and pulp_file: users see and manage only the objects they have
permissions on, and object creators automatically become owners.

## Built-in roles

| Role | Grants |
|---|---|
| `nuget.nugetrepository_creator` / `_owner` / `_viewer` | create / full control / read on repositories |
| `nuget.nugetremote_creator` / `_owner` / `_viewer` | the same, for remotes |
| `nuget.nugetdistribution_creator` / `_owner` / `_viewer` | the same, for distributions |
| `nuget.nugetdistribution_publisher` | push, unlist, and relist via the distribution's publish endpoint |
| `nuget.nugetcontentguard_creator` / `_owner` / `_viewer` | the same, for content guards |
| `nuget.nugetcontentguard_downloader` | download through a guarded distribution |

Roles can be granted globally, on a single object, or — with
[domains](site:pulpcore/docs/admin/guides/domain-multi-tenancy/) enabled — on a domain:

```bash
# global
http --auth admin:password POST :5001/pulp/api/v3/users/<id>/roles/ \
    role=nuget.nugetrepository_creator content_object:=null
# object-scoped
http --auth admin:password POST :5001<repo_href>add_role/ \
    role=nuget.nugetrepository_viewer users:='["alice"]'
```

## Uploading content

Uploading a package requires passing a `repository` the user is allowed to modify
(`nuget.modify_nugetrepository` plus view). Content queryset scoping shows users only
packages in repositories they can view.

## Domains

All endpoints, including the push/unlist publish endpoint, are domain-aware and operate
in the target distribution's domain.
