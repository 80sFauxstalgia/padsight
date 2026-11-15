# Builds a release and packages it as a zip in dist/.
#
#   powershell -ExecutionPolicy Bypass -File tools\package.ps1
#
# Output: dist\PadSight-<version>-win-x64.zip plus a .sha256 file next to it.
# User files (settings*.json, ctrl.last) and debug symbols are left out.
param([switch]$NoBuild)  # -NoBuild: package the existing Release output (e.g. while PadSight is running)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $NoBuild) {
    dotnet build VSCView.sln -c Release -nologo -v:minimal
    if ($LASTEXITCODE -ne 0) { throw "build failed" }
}

$bin = Join-Path $root 'VSCView\bin\Release\net462'
$version = (Get-Item (Join-Path $bin 'PadSight.exe')).VersionInfo.FileVersion -replace '\.0$', ''
$name = "PadSight-$version-win-x64"
$dist = Join-Path $root 'dist'
$stage = Join-Path $dist $name
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null

Get-ChildItem $bin -Recurse -File |
    Where-Object { $_.Extension -ne '.pdb' -and $_.Name -notlike 'settings*.json' -and $_.Name -ne 'ctrl.last' } |
    ForEach-Object {
        $rel = $_.FullName.Substring($bin.Length + 1)
        $dest = Join-Path $stage $rel
        New-Item -ItemType Directory -Force (Split-Path -Parent $dest) | Out-Null
        Copy-Item $_.FullName $dest
    }
Copy-Item (Join-Path $root 'LICENSE') (Join-Path $stage 'LICENSE.txt')
Copy-Item (Join-Path $root 'README.md') (Join-Path $stage 'README.md')
Copy-Item (Join-Path $root 'THIRD-PARTY-NOTICES.md') (Join-Path $stage 'THIRD-PARTY-NOTICES.md')

$zip = Join-Path $dist "$name.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
# Build the archive entry by entry: under Windows PowerShell 5 both Compress-Archive and
# ZipFile.CreateFromDirectory write '\' into entry names, which non-Windows unzip tools mishandle.
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open($zip, [IO.Compression.ZipArchiveMode]::Create)
try {
    Get-ChildItem $stage -Recurse -File | ForEach-Object {
        $entry = "$name/" + $_.FullName.Substring($stage.Length + 1).Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $_.FullName, $entry, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally { $archive.Dispose() }
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $name.zip" | Set-Content -Encoding ascii "$zip.sha256"
Write-Host "Packaged $zip"
Write-Host "SHA-256 $hash"
