Added ``NugetContentGuard`` for private feeds: it works like pulpcore's RBAC content
guard (grant the ``nuget.nugetcontentguard_downloader`` role), but challenges anonymous
requests with ``401 WWW-Authenticate: Basic`` so NuGet clients send the credentials from
``nuget.config``. The stock RBAC guard returns a plain 403, which real NuGet clients
cannot authenticate against.
