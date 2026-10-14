param(
    [switch]$SkipInstall,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$bundle = Join-Path $projectRoot "dist\AutoBard"
$archive = Join-Path $projectRoot "dist\AutoBard-win64.zip"
$checksum = "$archive.sha256"
$preserveRoot = $null
$preservedConfig = $false
$preservedDebug = $false

# Resolve all directories touched by recursive cleanup within this checkout.
$distRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "dist")) + [IO.Path]::DirectorySeparatorChar
if (-not ([IO.Path]::GetFullPath($bundle)).StartsWith($distRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Build output is outside the project's dist directory"
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found: $python"
}

Push-Location $projectRoot
try {
    $localConfig = Join-Path $bundle "config\settings.json"
    $localDebug = Join-Path $bundle "debug_output"
    if ((Test-Path -LiteralPath $localConfig) -or (Test-Path -LiteralPath $localDebug)) {
        $preserveRoot = Join-Path $projectRoot ("build\local-state-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $preserveRoot | Out-Null
        if (Test-Path -LiteralPath $localConfig) {
            New-Item -ItemType Directory -Path (Join-Path $preserveRoot "config") | Out-Null
            Copy-Item -LiteralPath $localConfig -Destination (Join-Path $preserveRoot "config\settings.json")
            $preservedConfig = $true
        }
        if (Test-Path -LiteralPath $localDebug) {
            Copy-Item -LiteralPath $localDebug -Destination $preserveRoot -Recurse
            $preservedDebug = $true
        }
    }

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
    if ($null -ne $preserveRoot -and (Test-Path -LiteralPath $preserveRoot)) {
        try {
            if (-not (Test-Path -LiteralPath $bundle)) {
                New-Item -ItemType Directory -Path $bundle | Out-Null
            }
            if ($preservedConfig) {
                $bundleConfig = Join-Path $bundle "config"
                if (-not (Test-Path -LiteralPath $bundleConfig)) {
                    New-Item -ItemType Directory -Path $bundleConfig | Out-Null
                }
                Copy-Item -LiteralPath (Join-Path $preserveRoot "config\settings.json") -Destination (Join-Path $bundleConfig "settings.json") -Force
            }
            if ($preservedDebug) {
                Copy-Item -LiteralPath (Join-Path $preserveRoot "debug_output") -Destination $bundle -Recurse -Force
            }
            $resolvedPreserve = (Resolve-Path -LiteralPath $preserveRoot).Path
            $allowedBuildRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "build")) + [IO.Path]::DirectorySeparatorChar
            if (-not $resolvedPreserve.StartsWith($allowedBuildRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Preserved state cleanup is outside the project's build directory"
            }
            Remove-Item -LiteralPath $resolvedPreserve -Recurse -Force
        } catch {
            Write-Warning "Could not restore local config/debug data. Preserved copy: $preserveRoot"
        }
    }
    Pop-Location
}
