$ErrorActionPreference = 'Stop'

$caseRoot = [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24')
$archive = [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\sample_bundle.tar.aes256')
$expectedArchiveHash = '2B990CF5FD361FC621C82DF024E3242A579C32BDD42FB06A8CB85F6A202120F5'
$residualArchive = [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\residual_bundle.tar.aes256')
$expectedResidualArchiveHash = '75F8B884FE1BE654FC9BBCAEB14D23C6FF87C1827D85DCA145CFCAFC2D57F760'
$outerArchive = [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\outer_original_bundle.tar.aes256')
$expectedOuterArchiveHash = '895CECB0409273AA7A7DE70D117DB3CF8139379DC5D79CEDA77AEE0A8FE5893D'
$cacheFile = [IO.Path]::GetFullPath('C:\ProgramData\853EAFC200002A0D\1')
$cacheDirectory = [IO.Path]::GetFullPath('C:\ProgramData\853EAFC200002A0D')

if ($caseRoot -ne 'D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24') {
    throw 'Unexpected quarantine root.'
}
if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    throw 'Encrypted quarantine archive is missing.'
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedArchiveHash) {
    throw 'Encrypted quarantine archive hash mismatch. No cleanup was performed.'
}
if (-not (Test-Path -LiteralPath $residualArchive -PathType Leaf)) {
    throw 'Encrypted residual archive is missing.'
}
if ((Get-FileHash -LiteralPath $residualArchive -Algorithm SHA256).Hash -ne $expectedResidualArchiveHash) {
    throw 'Encrypted residual archive hash mismatch. No cleanup was performed.'
}
if (-not (Test-Path -LiteralPath $outerArchive -PathType Leaf)) {
    throw 'Encrypted outer executable archive is missing.'
}
if ((Get-FileHash -LiteralPath $outerArchive -Algorithm SHA256).Hash -ne $expectedOuterArchiveHash) {
    throw 'Encrypted outer executable archive hash mismatch. No cleanup was performed.'
}

$temporaryDirectories = @(
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\staging'),
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\verify_roundtrip'),
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\residual_staging'),
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\residual_verify'),
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\outer_original_staging'),
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\outer_original_verify')
)
$temporaryFiles = @(
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\sample_bundle.tar'),
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\verify_roundtrip.tar'),
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\residual_bundle.tar'),
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\residual_verify.tar'),
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\outer_original_bundle.tar'),
    [IO.Path]::GetFullPath('D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\outer_original_verify.tar')
)

foreach ($path in $temporaryDirectories + $temporaryFiles) {
    if (-not $path.StartsWith($caseRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe cleanup target: $path"
    }
}

if (Test-Path -LiteralPath $cacheDirectory -PathType Container) {
    Remove-Item -LiteralPath $cacheDirectory -Recurse -Force
}

foreach ($path in $temporaryFiles) {
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
    }
}
foreach ($path in $temporaryDirectories) {
    if (Test-Path -LiteralPath $path -PathType Container) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

[pscustomobject]@{
    Archive = $archive
    ArchiveSHA256 = $expectedArchiveHash
    ResidualArchive = $residualArchive
    ResidualArchiveSHA256 = $expectedResidualArchiveHash
    OuterArchive = $outerArchive
    OuterArchiveSHA256 = $expectedOuterArchiveHash
    CacheDirectoryRemoved = -not (Test-Path -LiteralPath $cacheDirectory)
    PlainTarRemoved = -not (Test-Path -LiteralPath $temporaryFiles[0])
    StagingRemoved = -not (Test-Path -LiteralPath $temporaryDirectories[0])
}
