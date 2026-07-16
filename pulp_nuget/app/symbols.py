"""
Parsing utilities for NuGet symbol packages (.snupkg) and portable PDBs.

A .snupkg is a zip archive like a .nupkg, but its .nuspec declares the SymbolsPackage
package type and its payload is portable PDB files. Symbol servers address a PDB with
an SSQP key derived from the 20-byte PDB id in the portable PDB's #Pdb metadata stream:
https://github.com/dotnet/symstore/blob/main/docs/specs/SSQP_Key_Conventions.md
"""

import posixpath
import struct
import uuid
import zipfile
from gettext import gettext as _

from pulp_nuget.app.nuspec import InvalidNupkgError, parse_nuspec


class InvalidPdbError(InvalidNupkgError):
    """Raised when a file is not a valid portable PDB."""


def portable_pdb_signature(data):
    """
    The SSQP signature of a portable PDB: 40 lowercase hex characters.

    That is the 16-byte GUID at the start of the #Pdb stream's PDB id, rendered in GUID
    string order, plus the constant "ffffffff" age suffix. A debugger looking for
    foo.pdb requests <symbol-server>/foo.pdb/<signature>/foo.pdb.
    """
    # The portable PDB container is an ECMA-335 metadata root (II.24.2.1): a BSJB
    # header, a version string, and a table of named streams.
    if len(data) < 32 or data[:4] != b"BSJB":
        raise InvalidPdbError(_("The file is not a portable PDB."))
    try:
        (version_length,) = struct.unpack_from("<I", data, 12)
        offset = 16 + version_length
        (stream_count,) = struct.unpack_from("<H", data, offset + 2)
        offset += 4
        for _stream in range(stream_count):
            stream_offset, _stream_size = struct.unpack_from("<II", data, offset)
            offset += 8
            name_end = data.index(b"\0", offset)
            name = data[offset:name_end]
            # The stream name is null-terminated and padded to a 4-byte boundary.
            offset += (name_end - offset + 4) & ~3
            if name == b"#Pdb":
                pdb_id = data[stream_offset : stream_offset + 20]
                if len(pdb_id) != 20:
                    break
                return uuid.UUID(bytes_le=bytes(pdb_id[:16])).hex + "ffffffff"
    except (struct.error, ValueError):
        pass
    raise InvalidPdbError(_("The file is not a portable PDB (no #Pdb metadata stream)."))


def parse_snupkg(file_or_path):
    """
    Parse a .snupkg (path or file object) into package metadata plus its PDB records.

    Returns the manifest's package_id/version/version_normalized and pdb_files: one
    {"path", "name", "signature"} dict per portable PDB, where path is the archive
    member, name the lowercased basename, and signature the SSQP signature.
    """
    try:
        archive = zipfile.ZipFile(file_or_path)
    except zipfile.BadZipFile:
        raise InvalidNupkgError(_("The file is not a zip archive."))
    with archive:
        nuspec_names = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".nuspec") and "/" not in name
        ]
        if len(nuspec_names) != 1:
            raise InvalidNupkgError(
                _("Expected exactly one root-level .nuspec, found {}.").format(len(nuspec_names))
            )
        metadata = parse_nuspec(archive.read(nuspec_names[0]))
        type_names = {entry.get("name", "").lower() for entry in metadata["package_types"]}
        if "symbolspackage" not in type_names:
            raise InvalidNupkgError(
                _("A .snupkg must declare the SymbolsPackage package type in its .nuspec.")
            )
        pdb_files = []
        for name in archive.namelist():
            if not name.lower().endswith(".pdb"):
                continue
            try:
                signature = portable_pdb_signature(archive.read(name))
            except InvalidPdbError:
                raise InvalidPdbError(
                    _(
                        "'{}' is not a portable PDB; a .snupkg may only contain portable PDBs."
                    ).format(name)
                )
            record = {
                "path": name,
                "name": posixpath.basename(name).lower(),
                "signature": signature,
            }
            if record not in pdb_files:
                pdb_files.append(record)
    if not pdb_files:
        raise InvalidNupkgError(_("The .snupkg contains no .pdb files."))
    return {
        "package_id": metadata["package_id"],
        "version": metadata["version"],
        "version_normalized": metadata["version_normalized"],
        "pdb_files": pdb_files,
    }
