Packages can now be unlisted with ``dotnet nuget delete`` (DELETE on the publish
endpoint) and relisted with a POST to the same URL. Unlisted packages are hidden from
search and marked ``listed: false`` in registrations, but stay downloadable by exact
version, matching nuget.org semantics.
