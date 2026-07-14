from pulpcore.plugin import PulpPluginAppConfig


class PulpNugetPluginAppConfig(PulpPluginAppConfig):
    """Entry point for the nuget plugin."""

    name = "pulp_nuget.app"
    label = "nuget"
    version = "0.0.0.dev"
    python_package_name = "pulp_nuget"
    domain_compatible = True
