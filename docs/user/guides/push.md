# Push with the dotnet CLI

Every repository-backed distribution advertises a `PackagePublish/2.0.0` resource, so
`dotnet nuget push` works against it directly.

## Grant the push permission

Pushing requires the `nuget.publish_nugetdistribution` permission on the distribution.
Grant the built-in publisher role (object-scoped here — the user can push to this
distribution only):

```bash
http --auth admin:password POST :5001<distribution_href>add_role/ \
    role=nuget.nugetdistribution_publisher users:='["alice"]'
```

## Configure credentials and push

Authentication is HTTP basic via `packageSourceCredentials` in `nuget.config`. The
`X-NuGet-ApiKey` header is deliberately ignored, so pass any value for `--api-key`:

```bash
dotnet nuget add source http://<host>:<port>/pulp/content/foo/v3/index.json \
    --name pulp --username alice --password s3cret --store-password-in-clear-text
dotnet nuget push my.package.1.0.0.nupkg --source pulp --api-key unused
```

The push is processed as a Pulp task: the package is uploaded, parsed, and added to
the distribution's repository in a new repository version.
