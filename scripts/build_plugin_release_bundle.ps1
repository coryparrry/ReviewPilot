param(
    [string]$PluginSource = (Join-Path $PSScriptRoot "..\plugins\codex-review"),
    [string]$OutputRoot = (Join-Path $PSScriptRoot "..\artifacts\release-bundles"),
    [string]$BundleVersion,
    [switch]$IncludePycache
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[build-release] $Message"
}

function Should-SkipPath {
    param([string]$Path)

    if ($IncludePycache) {
        return $false
    }

    return $Path -split '[\\/]' -contains "__pycache__"
}

function Copy-Tree {
    param(
        [string]$SourceRoot,
        [string]$DestinationRoot
    )

    $items = Get-ChildItem -LiteralPath $SourceRoot -Recurse -Force |
        Where-Object { -not (Should-SkipPath $_.FullName) }

    foreach ($item in $items) {
        $relativePath = $item.FullName.Substring($SourceRoot.Length).TrimStart('\', '/')
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            continue
        }

        $targetPath = Join-Path $DestinationRoot $relativePath

        if ($item.PSIsContainer) {
            if (-not (Test-Path -LiteralPath $targetPath -PathType Container)) {
                New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
            }
            continue
        }

        $targetDirectory = Split-Path -Parent $targetPath
        if (-not (Test-Path -LiteralPath $targetDirectory -PathType Container)) {
            New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
        }

        Copy-Item -LiteralPath $item.FullName -Destination $targetPath -Force
    }
}

$resolvedPluginSource = (Resolve-Path -LiteralPath $PluginSource).Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$resolvedOutputRoot = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    [System.IO.Path]::GetFullPath($OutputRoot)
} else {
    [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $OutputRoot))
}

$pluginManifestPath = Join-Path $resolvedPluginSource ".codex-plugin\plugin.json"
if (-not (Test-Path -LiteralPath $pluginManifestPath -PathType Leaf)) {
    throw "Plugin manifest not found: $pluginManifestPath"
}

$pluginManifest = Get-Content -LiteralPath $pluginManifestPath -Raw | ConvertFrom-Json
$pluginName = [string]$pluginManifest.name
$pluginVersion = if ([string]::IsNullOrWhiteSpace($BundleVersion)) { [string]$pluginManifest.version } else { $BundleVersion }

if ([string]::IsNullOrWhiteSpace($pluginName)) {
    throw "Plugin manifest did not contain a plugin name."
}

if ([string]::IsNullOrWhiteSpace($pluginVersion)) {
    throw "Could not determine bundle version."
}

$bundleFolderName = "$pluginName-$pluginVersion"
$bundleRoot = Join-Path $resolvedOutputRoot $bundleFolderName
$zipPath = Join-Path $resolvedOutputRoot "$bundleFolderName.zip"
$stagingPluginRoot = Join-Path $bundleRoot "plugins\$pluginName"
$stagingScriptsRoot = Join-Path $bundleRoot "scripts"

if (Test-Path -LiteralPath $bundleRoot) {
    Remove-Item -LiteralPath $bundleRoot -Recurse -Force
}

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

New-Item -ItemType Directory -Path $stagingPluginRoot -Force | Out-Null
New-Item -ItemType Directory -Path $stagingScriptsRoot -Force | Out-Null

Copy-Tree -SourceRoot $resolvedPluginSource -DestinationRoot $stagingPluginRoot

$installScript = Join-Path $PSScriptRoot "install_plugin_to_codex.ps1"
$installNodeScript = Join-Path $PSScriptRoot "install_plugin_to_codex.mjs"
$syncScript = Join-Path $PSScriptRoot "sync_skill_to_codex.ps1"
$packageJson = Join-Path $PSScriptRoot "..\package.json"
$licenseFile = Join-Path $PSScriptRoot "..\LICENSE"

Copy-Item -LiteralPath $installScript -Destination (Join-Path $stagingScriptsRoot "install_plugin_to_codex.ps1") -Force
Copy-Item -LiteralPath $installNodeScript -Destination (Join-Path $stagingScriptsRoot "install_plugin_to_codex.mjs") -Force
Copy-Item -LiteralPath $syncScript -Destination (Join-Path $stagingScriptsRoot "sync_skill_to_codex.ps1") -Force
Copy-Item -LiteralPath $packageJson -Destination (Join-Path $bundleRoot "package.json") -Force
Copy-Item -LiteralPath $licenseFile -Destination (Join-Path $bundleRoot "LICENSE") -Force

$installGuide = @"
# Codex Review Plugin

Thanks for trying Codex Review.

## Quick install

1. Unzip this bundle.
2. Open a terminal inside the unzipped folder.
3. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_plugin_to_codex.ps1
```

4. Restart Codex Desktop if the plugin does not appear immediately.

If you prefer Node, you can also run:

```bash
node ./scripts/install_plugin_to_codex.mjs
```

## What this bundle contains

- `plugins/$pluginName`
  The plugin bundle Codex Desktop installs from.
- `scripts/install_plugin_to_codex.ps1`
  Copies the plugin into your local Codex marketplace path.
- `scripts/install_plugin_to_codex.mjs`
  Node-based installer for the same Codex Desktop plugin path.
- `scripts/sync_skill_to_codex.ps1`
  Optional helper for the direct runtime skill copy.
- `package.json`
  npm package metadata for producing an installer tarball.
- `LICENSE`
  The MIT license text for the public release bundle.

## Notes

- The installer writes into `~/.codex/local-marketplaces/`.
- You do not need to clone the source repo just to try the plugin from this bundle.
"@

Set-Content -LiteralPath (Join-Path $bundleRoot "README-INSTALL.md") -Value $installGuide -Encoding utf8

if (-not (Test-Path -LiteralPath $resolvedOutputRoot -PathType Container)) {
    New-Item -ItemType Directory -Path $resolvedOutputRoot -Force | Out-Null
}

Compress-Archive -Path (Join-Path $bundleRoot "*") -DestinationPath $zipPath -Force

$packageJsonBackup = $null
if ($BundleVersion) {
    $packageJsonBackup = Join-Path $resolvedOutputRoot "package.json.bak"
    Copy-Item -LiteralPath $packageJson -Destination $packageJsonBackup -Force
    try {
        $packagePayload = Get-Content -LiteralPath $packageJson -Raw | ConvertFrom-Json
        $packagePayload.version = $pluginVersion
        $packagePayload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $packageJson -Encoding utf8
    } catch {
        if (Test-Path -LiteralPath $packageJsonBackup) {
            Move-Item -LiteralPath $packageJsonBackup -Destination $packageJson -Force
        }
        throw
    }
}

Push-Location $repoRoot
try {
    & npm pack --pack-destination $resolvedOutputRoot | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "npm pack failed."
    }
} finally {
    Pop-Location
    if ($packageJsonBackup -and (Test-Path -LiteralPath $packageJsonBackup)) {
        Move-Item -LiteralPath $packageJsonBackup -Destination $packageJson -Force
    }
}

Write-Step "Built release folder $bundleRoot"
Write-Step "Built release archive $zipPath"
Write-Step "Built npm package tarball in $resolvedOutputRoot"
