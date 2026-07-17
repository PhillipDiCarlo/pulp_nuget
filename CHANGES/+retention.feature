Added ``retain_package_versions`` to repositories: when set, every new repository
version keeps only that many versions of each package id (newest by NuGet
precedence), applied to packages and symbol packages alike on sync, push, upload,
and modify.
