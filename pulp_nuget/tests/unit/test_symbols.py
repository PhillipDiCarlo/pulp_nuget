"""Unit tests for symbol-package parsing: portable PDB signatures and .snupkg archives."""

import io
import struct
import uuid
import zipfile

import pytest

from pulp_nuget.app.nuspec import InvalidNupkgError
from pulp_nuget.app.symbols import InvalidPdbError, parse_snupkg, portable_pdb_signature


def build_portable_pdb(pdb_id, leading_streams=()):
    """
    A minimal ECMA-335 metadata root with a #Pdb stream holding the 20-byte PDB id.

    leading_streams places named dummy streams before #Pdb to exercise header walking.
    """
    streams = [(name, b"\0" * 8) for name in leading_streams] + [("#Pdb", pdb_id)]
    version = b"PDB v1.0" + b"\0" * 4
    prefix = (
        b"BSJB" + struct.pack("<HH", 1, 1) + b"\0" * 4 + struct.pack("<I", len(version)) + version
    )
    header_tail = struct.pack("<HH", 0, len(streams))
    headers_size = sum(8 + ((len(name) + 1 + 3) & ~3) for name, _ in streams)
    data_offset = len(prefix) + len(header_tail) + headers_size
    headers = b""
    body = b""
    for name, data in streams:
        headers += struct.pack("<II", data_offset + len(body), len(data))
        name_bytes = name.encode() + b"\0"
        headers += name_bytes + b"\0" * (-len(name_bytes) % 4)
        body += data
    return prefix + header_tail + headers + body


def test_signature_guid_byte_order():
    """The signature renders the GUID in string order (mixed endianness) plus ffffffff."""
    pdb_id = bytes(range(16)) + b"\x01\x00\x00\x00"
    blob = build_portable_pdb(pdb_id)
    assert portable_pdb_signature(blob) == "03020100050407060809" + "0a0b0c0d0e0f" + "ffffffff"


def test_signature_roundtrips_uuid():
    guid = uuid.uuid4()
    blob = build_portable_pdb(guid.bytes_le + b"\x01\x00\x00\x00", leading_streams=("#~",))
    assert portable_pdb_signature(blob) == guid.hex + "ffffffff"


def test_signature_skips_other_streams():
    guid = uuid.uuid4()
    blob = build_portable_pdb(
        guid.bytes_le + b"\xff\xff\xff\xff", leading_streams=("#~", "#Strings", "#US", "#GUID")
    )
    assert portable_pdb_signature(blob) == guid.hex + "ffffffff"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"MZ" + b"\0" * 100,  # a Windows (native) PDB starts differently too
        b"Microsoft C/C++ MSF 7.00\r\n" + b"\0" * 100,  # native PDB header
        b"BSJB" + b"\0" * 10,  # truncated
        build_portable_pdb(bytes(20))[:40],  # cut off inside the stream table
    ],
)
def test_signature_rejects_non_portable_pdbs(data):
    with pytest.raises(InvalidPdbError):
        portable_pdb_signature(data)


def test_signature_requires_pdb_stream():
    blob = build_portable_pdb(bytes(20))
    # Rebuild with the #Pdb stream renamed away.
    blob = blob.replace(b"#Pdb\0", b"#Xdb\0")
    with pytest.raises(InvalidPdbError):
        portable_pdb_signature(blob)


NUSPEC_TEMPLATE = """<?xml version="1.0"?>
<package xmlns="http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd">
  <metadata>
    <id>{package_id}</id>
    <version>{version}</version>
    <authors>tests</authors>
    <description>A synthetic symbol package.</description>
    {package_types}
  </metadata>
</package>"""

SYMBOLS_TYPE = '<packageTypes><packageType name="SymbolsPackage" /></packageTypes>'


def build_snupkg(package_id="Test.Pkg", version="1.0.0", package_types=SYMBOLS_TYPE, pdbs=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            f"{package_id}.nuspec",
            NUSPEC_TEMPLATE.format(
                package_id=package_id, version=version, package_types=package_types
            ),
        )
        for path, data in pdbs:
            archive.writestr(path, data)
    buffer.seek(0)
    return buffer


def test_parse_snupkg():
    guid = uuid.uuid4()
    pdb = build_portable_pdb(guid.bytes_le + b"\x01\x00\x00\x00")
    snupkg = build_snupkg(
        version="1.0.0.0",
        pdbs=[("lib/net8.0/Test.Pkg.pdb", pdb), ("lib/net6.0/Test.Pkg.pdb", pdb)],
    )
    metadata = parse_snupkg(snupkg)
    assert metadata["package_id"] == "Test.Pkg"
    assert metadata["version"] == "1.0.0.0"
    assert metadata["version_normalized"] == "1.0.0"
    signature = guid.hex + "ffffffff"
    assert metadata["pdb_files"] == [
        {"path": "lib/net8.0/Test.Pkg.pdb", "name": "test.pkg.pdb", "signature": signature},
        {"path": "lib/net6.0/Test.Pkg.pdb", "name": "test.pkg.pdb", "signature": signature},
    ]


def test_parse_snupkg_requires_symbols_package_type():
    pdb = build_portable_pdb(bytes(20))
    snupkg = build_snupkg(package_types="", pdbs=[("lib/Test.Pkg.pdb", pdb)])
    with pytest.raises(InvalidNupkgError, match="SymbolsPackage"):
        parse_snupkg(snupkg)


def test_parse_snupkg_rejects_native_pdbs():
    native_pdb = b"Microsoft C/C++ MSF 7.00\r\n" + b"\0" * 64
    snupkg = build_snupkg(pdbs=[("lib/Test.Pkg.pdb", native_pdb)])
    with pytest.raises(InvalidPdbError, match="portable"):
        parse_snupkg(snupkg)


def test_parse_snupkg_requires_pdbs():
    with pytest.raises(InvalidNupkgError, match="no .pdb files"):
        parse_snupkg(build_snupkg())


def test_parse_snupkg_rejects_non_zip():
    with pytest.raises(InvalidNupkgError, match="zip"):
        parse_snupkg(io.BytesIO(b"not a zip"))
