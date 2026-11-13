from django.db import migrations

BATCH_SIZE = 1000


def fix_dependency_groups(groups):
    """Rename the "version" key that sync used to store to "range"; True if changed."""
    changed = False
    for group in groups:
        for dependency in group.get("dependencies", []):
            if "version" in dependency:
                version = dependency.pop("version")
                if version and "range" not in dependency:
                    dependency["range"] = version
                changed = True
            for key in ("include", "exclude"):
                if dependency.get(key) == "":
                    del dependency[key]
                    changed = True
    return changed


def fix_synced_dependency_ranges(apps, schema_editor):
    """
    Synced packages stored each dependency's version range under "version", but the
    registration builder reads "range" (what uploaded packages store), so their
    dependencies were served as accepting any version.
    """
    NugetPackageContent = apps.get_model("nuget", "NugetPackageContent")
    batch = []
    packages = NugetPackageContent.objects.exclude(dependency_groups=[]).only("dependency_groups")
    for package in packages.iterator(chunk_size=BATCH_SIZE):
        if fix_dependency_groups(package.dependency_groups):
            batch.append(package)
        if len(batch) >= BATCH_SIZE:
            NugetPackageContent.objects.bulk_update(batch, ["dependency_groups"])
            batch = []
    if batch:
        NugetPackageContent.objects.bulk_update(batch, ["dependency_groups"])


class Migration(migrations.Migration):

    dependencies = [
        ("nuget", "0009_nugetalternatecontentsource"),
    ]

    operations = [
        migrations.RunPython(
            fix_synced_dependency_ranges, reverse_code=migrations.RunPython.noop, elidable=True
        ),
    ]
