from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    url: str
    size: int


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    page_url: str
    notes: str
    package: ReleaseAsset
    checksum: ReleaseAsset


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    version: str
    payload_dir: Path
    temporary_dir: Path
    notes: str


ProgressCallback = Callable[[int, int], None]


def _version_key(value: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(
        r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+](.+))?",
        value.strip(),
        flags=re.IGNORECASE,
    )
    if match is None:
        raise UpdateError(f"无法识别版本号：{value}")
    major, minor, patch = (int(part or 0) for part in match.groups()[:3])
    stable = 0 if match.group(4) else 1
    return major, minor, patch, stable


def is_newer_version(candidate: str, current: str) -> bool:
    return _version_key(candidate) > _version_key(current)


class GitHubUpdater:
    def __init__(
        self,
        repository: str,
        current_version: str,
        asset_name: str = "AutoBard-win64.zip",
        timeout_s: float = 15.0,
    ) -> None:
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
            raise ValueError("GitHub repository must use the owner/name format")
        self.repository = repository
        self.current_version = current_version
        self.asset_name = asset_name
        self.timeout_s = max(1.0, float(timeout_s))

    def _request(self, url: str) -> urllib.request.Request:
        if not url.startswith("https://"):
            raise UpdateError("更新下载只允许 HTTPS")
        return urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"AutoBard/{self.current_version}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def check(self) -> UpdateInfo | None:
        url = f"https://api.github.com/repos/{self.repository}/releases/latest"
        try:
            with urllib.request.urlopen(self._request(url), timeout=self.timeout_s) as response:
                raw = response.read(2_000_000)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise UpdateError(f"GitHub 返回 HTTP {exc.code}") from exc
        except OSError as exc:
            raise UpdateError(f"无法连接 GitHub：{exc}") from exc

        try:
            release = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError("GitHub 更新信息格式无效") from exc
        if not isinstance(release, dict) or release.get("draft"):
            return None

        version = str(release.get("tag_name", "")).strip()
        if not version or not is_newer_version(version, self.current_version):
            return None

        assets: dict[str, ReleaseAsset] = {}
        for value in release.get("assets", []):
            if not isinstance(value, dict):
                continue
            name = str(value.get("name", ""))
            download_url = str(value.get("browser_download_url", ""))
            if name and download_url.startswith("https://"):
                assets[name] = ReleaseAsset(name, download_url, int(value.get("size", 0)))

        package = assets.get(self.asset_name)
        checksum = assets.get(f"{self.asset_name}.sha256")
        if package is None or checksum is None:
            raise UpdateError(
                f"最新版本缺少 {self.asset_name} 或对应的 .sha256 校验文件"
            )
        return UpdateInfo(
            version=version.removeprefix("v"),
            page_url=str(release.get("html_url", "")),
            notes=str(release.get("body", "")),
            package=package,
            checksum=checksum,
        )

    def _read_checksum(self, asset: ReleaseAsset) -> str:
        try:
            with urllib.request.urlopen(
                self._request(asset.url), timeout=self.timeout_s
            ) as response:
                value = response.read(4096).decode("ascii", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            raise UpdateError(f"无法下载更新校验文件：{exc}") from exc
        match = re.search(r"\b([0-9a-fA-F]{64})\b", value)
        if match is None:
            raise UpdateError("SHA-256 校验文件格式无效")
        return match.group(1).lower()

    def prepare(
        self,
        update: UpdateInfo,
        progress: ProgressCallback | None = None,
    ) -> PreparedUpdate:
        expected_hash = self._read_checksum(update.checksum)
        temporary_dir = Path(tempfile.mkdtemp(prefix="autobard-update-"))
        archive = temporary_dir / self.asset_name
        try:
            digest = hashlib.sha256()
            downloaded = 0
            try:
                with urllib.request.urlopen(
                    self._request(update.package.url), timeout=self.timeout_s
                ) as response, archive.open("wb") as output:
                    total = int(response.headers.get("Content-Length") or update.package.size or 0)
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        if progress is not None:
                            progress(downloaded, total)
            except OSError as exc:
                raise UpdateError(f"更新包下载失败：{exc}") from exc

            if digest.hexdigest().lower() != expected_hash:
                raise UpdateError("更新包 SHA-256 校验失败，已拒绝安装")

            extracted = temporary_dir / "payload"
            extracted.mkdir()
            self._extract_safely(archive, extracted)
            executables = list(extracted.rglob("AutoBard.exe"))
            if len(executables) != 1:
                raise UpdateError("更新包中没有唯一的 AutoBard.exe")
            payload_dir = executables[0].parent
            return PreparedUpdate(
                version=update.version,
                payload_dir=payload_dir,
                temporary_dir=temporary_dir,
                notes=update.notes,
            )
        except Exception:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            raise

    @staticmethod
    def _extract_safely(archive: Path, destination: Path) -> None:
        destination_resolved = destination.resolve()
        try:
            with zipfile.ZipFile(archive) as package:
                for info in package.infolist():
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise UpdateError("更新包不能包含符号链接")
                    target = (destination / info.filename).resolve()
                    if not target.is_relative_to(destination_resolved):
                        raise UpdateError("更新包包含不安全的文件路径")
                package.extractall(destination)
        except (OSError, zipfile.BadZipFile) as exc:
            raise UpdateError(f"无法解压更新包：{exc}") from exc


def launch_windows_installer(
    prepared: PreparedUpdate,
    install_dir: Path,
    process_id: int | None = None,
) -> None:
    if os.name != "nt":
        raise UpdateError("自动安装目前只支持 Windows")
    process_id = int(process_id or os.getpid())
    install_dir = install_dir.resolve()
    executable = install_dir / "AutoBard.exe"
    if not executable.exists():
        raise UpdateError("自动安装只能从打包后的 AutoBard.exe 中运行")

    script = prepared.temporary_dir / "install-update.ps1"
    script.write_text(
        r'''param(
    [Parameter(Mandatory=$true)][int]$OldProcessId,
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$Executable
)
$ErrorActionPreference = "Stop"
try {
    Wait-Process -Id $OldProcessId -Timeout 60 -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    $arguments = @($Source, $Target, "/E", "/R:3", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XD", (Join-Path $Source "config"), (Join-Path $Source "debug_output"))
    $copy = Start-Process -FilePath "robocopy.exe" -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($copy.ExitCode -ge 8) {
        throw "robocopy failed with exit code $($copy.ExitCode)"
    }
    Start-Process -FilePath $Executable -WorkingDirectory $Target
} catch {
    $_ | Out-File -FilePath (Join-Path $Target "update-error.log") -Encoding utf8
    if (Test-Path -LiteralPath $Executable) {
        Start-Process -FilePath $Executable -WorkingDirectory $Target
    }
} finally {
    Remove-Item -LiteralPath (Split-Path -Parent $Source) -Recurse -Force -ErrorAction SilentlyContinue
}
''',
        encoding="utf-8-sig",
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-OldProcessId",
            str(process_id),
            "-Source",
            str(prepared.payload_dir),
            "-Target",
            str(install_dir),
            "-Executable",
            str(executable),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        close_fds=True,
    )


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()
