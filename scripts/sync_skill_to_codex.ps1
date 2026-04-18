param(
    [string]$Source = (Join-Path $PSScriptRoot "..\plugins\codex-review\skills\bug-hunting-code-review"),
    [string]$Destination = (Join-Path $HOME ".codex\skills\bug-hunting-code-review"),
    [switch]$DryRun,
    [switch]$IncludePycache
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[sync] $Message"
}

function Should-SkipPath {
    param([string]$Path)

    if ($IncludePycache) {
        return $false
    }

    return $Path -split '[\\/]' -contains "__pycache__"
}

$resolvedSource = (Resolve-Path -LiteralPath $Source).Path

if (-not (Test-Path -LiteralPath $resolvedSource -PathType Container)) {
    throw "Source skill directory not found: $Source"
}

$destinationExists = Test-Path -LiteralPath $Destination -PathType Container
if (-not $destinationExists) {
    if ($DryRun) {
        Write-Step "Would create destination directory $Destination"
    } else {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
        Write-Step "Created destination directory $Destination"
    }
}

$copiedFiles = 0
$createdDirectories = 0

$directories = Get-ChildItem -LiteralPath $resolvedSource -Directory -Recurse -Force |
    Where-Object { -not (Should-SkipPath $_.FullName) }

foreach ($directory in $directories) {
    $relativePath = $directory.FullName.Substring($resolvedSource.Length).TrimStart('\', '/')
    $targetDirectory = Join-Path $Destination $relativePath

    if (-not (Test-Path -LiteralPath $targetDirectory -PathType Container)) {
        if ($DryRun) {
            Write-Step "Would create directory $targetDirectory"
        } else {
            New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
        }
        $createdDirectories++
    }
}

$files = Get-ChildItem -LiteralPath $resolvedSource -File -Recurse -Force |
    Where-Object { -not (Should-SkipPath $_.FullName) }

foreach ($file in $files) {
    $relativePath = $file.FullName.Substring($resolvedSource.Length).TrimStart('\', '/')
    $targetFile = Join-Path $Destination $relativePath
    $targetDirectory = Split-Path -Parent $targetFile

    if (-not (Test-Path -LiteralPath $targetDirectory -PathType Container)) {
        if ($DryRun) {
            Write-Step "Would create directory $targetDirectory"
        } else {
            New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
        }
        $createdDirectories++
    }

    if ($DryRun) {
        Write-Step "Would copy $relativePath"
    } else {
        Copy-Item -LiteralPath $file.FullName -Destination $targetFile -Force
    }
    $copiedFiles++
}

$mode = if ($DryRun) { "dry-run" } else { "sync" }
Write-Step "Completed $mode from $resolvedSource to $Destination"
Write-Step "Directories created: $createdDirectories"
Write-Step "Files processed: $copiedFiles"
Write-Step "Deletes are not propagated. Re-run with a clean destination only if you intentionally want mirror semantics."
