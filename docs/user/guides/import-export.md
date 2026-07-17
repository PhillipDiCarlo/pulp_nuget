# Export and Import Repositories

Move a repository between Pulp instances without network connectivity between them —
the usual air-gap workflow. Exports carry packages and symbol packages with all their
parsed metadata.

## On the connected instance: export

The admin must allow the filesystem location first (`ALLOWED_EXPORT_PATHS` in the
settings). Then create an exporter for one or more repositories and run it:

```bash
http --auth admin:password POST :5001/pulp/api/v3/exporters/core/pulp/ \
    name=airgap path=/exports/nuget repositories:='["<repo_href>"]'
http --auth admin:password POST :5001<exporter_href>exports/ body:='{}'
```

The export task writes a `.tar.gz` archive (path and checksum are in the export's
`output_file_info`) containing the repository's latest version: content rows,
artifacts, and metadata.

## On the air-gapped instance: import

Transfer the archive, allow the location with `ALLOWED_IMPORT_PATHS`, and map the
source repository name to a destination repository:

```bash
http --auth admin:password POST :5001/pulp/api/v3/repositories/nuget/nuget/ name=mirror
http --auth admin:password POST :5001/pulp/api/v3/importers/core/pulp/ \
    name=airgap repo_mapping:='{"<source repo name>": "mirror"}'
http --auth admin:password POST :5001<importer_href>imports/ \
    path=/imports/<archive>.tar.gz
```

The import creates a new repository version in `mirror` with the exported packages;
a distribution pointing at it serves them immediately.
