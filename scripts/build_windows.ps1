param(
    [switch]$SkipInstall,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found: $python"
}

Push-Location $projectRoot
try {
    if (-not $SkipInstall) {
        & $python -m pip install -e ".[windows-fast,build]"
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
    }
    if (-not $SkipTests) {
        & $python -m pytest
        if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
    }

    & $python -m PyInstaller --noconfirm --clean AutoBard.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

    $bundle = Join-Path $projectRoot "dist\AutoBard"
    $archive = Join-Path $projectRoot "dist\AutoBard-win64.zip"
    $checksum = "$archive.sha256"
    if (-not (Test-Path -LiteralPath (Join-Path $bundle "AutoBard.exe"))) {
        throw "AutoBard.exe was not produced"
    }
    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $checksum -Force -ErrorAction SilentlyContinue
    $compressed = $false
    for ($attempt = 1; $attempt -le 5 -and -not $compressed; $attempt++) {
        try {
            Compress-Archive -Path (Join-Path $bundle "*") -DestinationPath $archive -CompressionLevel Optimal
            $compressed = $true
        } catch {
            Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
            if ($attempt -eq 5) { throw }
            Start-Sleep -Seconds 2
        }
    }
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText($checksum, "$hash  AutoBard-win64.zip`n", [Text.UTF8Encoding]::new($false))

    Write-Host "Build complete: $bundle"
    Write-Host "Release assets: $archive and $checksum"
} finally {
    Pop-Location
}
