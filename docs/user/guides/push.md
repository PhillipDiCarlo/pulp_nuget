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

## Symbol packages (.snupkg)

The service index also advertises a `SymbolPackagePublish/4.9.0` resource, so symbol
packages push the same way — both explicitly and via the automatic symbol push that
`dotnet nuget push my.package.1.0.0.nupkg` performs when a matching `.snupkg` sits
next to the `.nupkg`:

```bash
dotnet nuget push my.package.1.0.0.snupkg --source pulp --api-key unused
```

A pushed `.snupkg` must declare the `SymbolsPackage` package type in its `.nuspec` and
may only contain portable PDBs (what `dotnet pack --include-symbols
-p:SymbolPackageFormat=snupkg` produces). At push time each PDB's identity is
extracted, and the distribution then acts as a symbol server: debuggers can fetch
PDBs from

```
http://<host>:<port>/pulp/content/foo/symbols/
```

Add that URL as a symbol server in Visual Studio (Tools > Options > Debugging >
Symbols) or query it with `dotnet-symbol`. The `.snupkg` itself is also downloadable
at `v3-flatcontainer/{id}/{version}/{id}.{version}.snupkg`.
