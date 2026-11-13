"""Unit tests for alternate content source matching and downloads."""

import asyncio
from types import SimpleNamespace

import pytest

from pulpcore.plugin.stages import models as stage_models

from pulp_nuget.app.tasks import synchronizing
from pulp_nuget.app.tasks.synchronizing import NugetDeclarativeArtifact, group_acs_sources


class FakeArtifact:
    """Stands in for Artifact, whose constructor queries the database for the domain."""

    def __init__(self, file=None, **attributes):
        self.file = file
        self.size = attributes.get("size")

    def __getattr__(self, name):
        # No expected digests (sha256, ...) are known before a NuGet download.
        return None


@pytest.fixture(autouse=True)
def fake_artifact(monkeypatch):
    monkeypatch.setattr(synchronizing, "Artifact", FakeArtifact)
    monkeypatch.setattr(stage_models, "Artifact", FakeArtifact)


class FakeRemote:
    """A remote whose downloads succeed or fail per URL, recording every attempt."""

    def __init__(self, name, failing_urls=(), attempts=None):
        self.name = name
        self.failing_urls = set(failing_urls)
        self.attempts = attempts if attempts is not None else []

    def get_downloader(self, url, **kwargs):
        remote = self

        class Downloader:
            async def run(self, extra_data=None):
                remote.attempts.append((remote.name, url))
                if url in remote.failing_urls:
                    raise OSError(f"cannot fetch {url}")
                return SimpleNamespace(artifact_attributes={"size": 1}, path=f"/tmp/{remote.name}")

        return Downloader()


def _artifact(remote, alternate_sources):
    d_artifact = NugetDeclarativeArtifact(
        artifact=FakeArtifact(),
        url="https://upstream/pkg.1.0.0.nupkg",
        relative_path="pkg/1.0.0/pkg.1.0.0.nupkg",
        remote=remote,
    )
    d_artifact.alternate_sources = alternate_sources
    return d_artifact


def test_group_acs_sources_keeps_preference_order():
    keys = {1: ("a", "1.0.0"), 2: ("b", "2.0.0")}
    acs_one, acs_two = object(), object()
    rows = [
        (1, acs_one, "https://one/a.1.0.0.nupkg"),
        (2, acs_one, "https://one/b.2.0.0.nupkg"),
        (1, acs_two, "https://two/a.1.0.0.nupkg"),
        # Content outside the requested keys is ignored.
        (3, acs_two, "https://two/c.3.0.0.nupkg"),
    ]
    assert group_acs_sources(keys, rows) == {
        ("a", "1.0.0"): [
            (acs_one, "https://one/a.1.0.0.nupkg"),
            (acs_two, "https://two/a.1.0.0.nupkg"),
        ],
        ("b", "2.0.0"): [(acs_one, "https://one/b.2.0.0.nupkg")],
    }
    assert group_acs_sources(keys, []) == {}


@pytest.mark.parametrize(
    "failing, expected_path, expected_attempts",
    [
        # The first ACS copy wins; the remote is never contacted.
        ((), "/tmp/acs-one", [("acs-one", "https://one/pkg")]),
        # A failing copy falls through to the next ACS, with that ACS's own remote.
        (
            ("https://one/pkg",),
            "/tmp/acs-two",
            [("acs-one", "https://one/pkg"), ("acs-two", "https://two/pkg")],
        ),
        # When every copy fails, the sync remote downloads its own url.
        (
            ("https://one/pkg", "https://two/pkg"),
            "/tmp/remote",
            [
                ("acs-one", "https://one/pkg"),
                ("acs-two", "https://two/pkg"),
                ("remote", "https://upstream/pkg.1.0.0.nupkg"),
            ],
        ),
    ],
)
def test_download_tries_alternate_sources_first(failing, expected_path, expected_attempts):
    attempts = []
    remote = FakeRemote("remote", attempts=attempts)
    acs_one = FakeRemote("acs-one", failing, attempts)
    acs_two = FakeRemote("acs-two", failing, attempts)
    d_artifact = _artifact(remote, [(acs_one, "https://one/pkg"), (acs_two, "https://two/pkg")])

    result = asyncio.run(d_artifact.download())

    assert result.path == expected_path
    assert attempts == expected_attempts
    # The sync remote stays the artifact's remote, so its remote artifact is still saved.
    assert d_artifact.remote is remote
    assert d_artifact.url == "https://upstream/pkg.1.0.0.nupkg"


def test_download_without_alternate_sources_uses_the_remote():
    attempts = []
    remote = FakeRemote("remote", attempts=attempts)
    result = asyncio.run(_artifact(remote, []).download())
    assert result.path == "/tmp/remote"
    assert attempts == [("remote", "https://upstream/pkg.1.0.0.nupkg")]
