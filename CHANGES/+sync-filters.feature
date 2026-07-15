Added sync filtering: remotes gained an ``excludes`` list, and both ``includes`` and
``excludes`` entries may now carry a NuGet version range (e.g. ``"Serilog [2.0,3.0)"``).
Include ranges match prerelease versions only when a bound has a prerelease label;
exclude ranges match by pure precedence. Range filters also skip downloading
registration pages that cannot contain matching versions.
