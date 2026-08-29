from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile

import pytest

from autobard.updater import GitHubUpdater, UpdateError, is_newer_version


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._data.read(size)


def test_version_comparison() -> None:
    assert is_newer_version("v2.1.0", "2.0.9")
    assert not is_newer_version("2.0.0", "2.0.0")
    assert not is_newer_version("2.0.0-beta", "2.0.0")


def test_check_and_prepare_verified_release(monkeypatch) -> None:
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as package:
        package.writestr("AutoBard.exe", b"test executable")
        package.writestr("_internal/runtime.dat", b"runtime")
    archive = archive_buffer.getvalue()
    digest = hashlib.sha256(archive).hexdigest().encode("ascii")
    release = json.dumps(
        {
            "tag_name": "v2.1.0",
            "draft": False,
            "html_url": "https://github.com/nexor-source/AutoBard/releases/tag/v2.1.0",
            "body": "Update notes",
            "assets": [
                {
                    "name": "AutoBard-win64.zip",
                    "browser_download_url": "https://example.test/AutoBard-win64.zip",
                    "size": len(archive),
                },
                {
                    "name": "AutoBard-win64.zip.sha256",
                    "browser_download_url": "https://example.test/AutoBard-win64.zip.sha256",
                    "size": len(digest),
                },
            ],
        }
    ).encode("utf-8")

    def fake_urlopen(request, timeout):
        del timeout
        if request.full_url.endswith("releases/latest"):
            return FakeResponse(release)
        if request.full_url.endswith(".sha256"):
            return FakeResponse(digest + b"  AutoBard-win64.zip\n")
        return FakeResponse(archive)

    monkeypatch.setattr("autobard.updater.urllib.request.urlopen", fake_urlopen)
    updater = GitHubUpdater("nexor-source/AutoBard", "2.0.0")
    info = updater.check()
    assert info is not None

    prepared = updater.prepare(info)
    try:
        assert prepared.version == "2.1.0"
        assert (prepared.payload_dir / "AutoBard.exe").read_bytes() == b"test executable"
    finally:
        shutil.rmtree(prepared.temporary_dir, ignore_errors=True)


def test_safe_extract_rejects_parent_path(tmp_path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("../outside.txt", b"no")

    with pytest.raises(UpdateError, match="不安全"):
        GitHubUpdater._extract_safely(archive, tmp_path / "output")
