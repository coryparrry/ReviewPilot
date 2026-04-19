param(
    [string]$Source = (Join-Path $PSScriptRoot "..\plugins\codex-review"),
    [string]$MarketplaceRoot = (Join-Path $HOME ".codex\local-marketplaces\codex-review-local"),
    [switch]$DryRun,
    [switch]$IncludePycache
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[install-plugin] $Message"
}

function Ensure-Directory {
    param(
        [string]$Path,
        [switch]$DryRunMode
    )

    if (Test-Path -LiteralPath $Path -PathType Container) {
        return
    }

    if ($DryRunMode) {
        Write-Step "Would create directory $Path"
        return
    }

    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    Write-Step "Created directory $Path"
}

function Should-SkipPath {
    param([string]$Path)

    if ($IncludePycache) {
        return $false
    }

    return $Path -split '[\\/]' -contains "__pycache__"
}

$resolvedSource = (Resolve-Path -LiteralPath $Source).Path
$resolvedMarketplaceRoot = if ([System.IO.Path]::IsPathRooted($MarketplaceRoot)) {
    [System.IO.Path]::GetFullPath($MarketplaceRoot)
} else {
    [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $MarketplaceRoot))
}
$pluginManifestPath = Join-Path $resolvedSource ".codex-plugin\plugin.json"

if (-not (Test-Path -LiteralPath $resolvedSource -PathType Container)) {
    throw "Plugin source directory not found: $Source"
}

if (-not (Test-Path -LiteralPath $pluginManifestPath -PathType Leaf)) {
    throw "Plugin manifest not found: $pluginManifestPath"
}

$pluginManifest = Get-Content -LiteralPath $pluginManifestPath -Raw | ConvertFrom-Json
$pluginName = [string]$pluginManifest.name

if ([string]::IsNullOrWhiteSpace($pluginName)) {
    throw "Plugin manifest did not contain a plugin name."
}

$pluginsRoot = Join-Path $resolvedMarketplaceRoot "plugins"
$pluginDestination = Join-Path $pluginsRoot $pluginName
$agentsPluginsRoot = Join-Path $resolvedMarketplaceRoot ".agents\plugins"
$marketplaceJsonPath = Join-Path $agentsPluginsRoot "marketplace.json"

Ensure-Directory -Path $resolvedMarketplaceRoot -DryRunMode:$DryRun
Ensure-Directory -Path $pluginsRoot -DryRunMode:$DryRun
Ensure-Directory -Path $agentsPluginsRoot -DryRunMode:$DryRun

if (-not (Test-Path -LiteralPath $pluginDestination -PathType Container)) {
    if ($DryRun) {
        Write-Step "Would create plugin destination $pluginDestination"
    } else {
        New-Item -ItemType Directory -Path $pluginDestination -Force | Out-Null
        Write-Step "Created plugin destination $pluginDestination"
    }
}

$sourceFiles = Get-ChildItem -LiteralPath $resolvedSource -Recurse -Force |
    Where-Object { -not (Should-SkipPath $_.FullName) }
$copiedFiles = 0
$createdDirectories = 0

foreach ($item in $sourceFiles) {
    $relativePath = $item.FullName.Substring($resolvedSource.Length).TrimStart('\', '/')
    if ([string]::IsNullOrWhiteSpace($relativePath)) {
        continue
    }

    $targetPath = Join-Path $pluginDestination $relativePath

    if ($item.PSIsContainer) {
        if (-not (Test-Path -LiteralPath $targetPath -PathType Container)) {
            if ($DryRun) {
                Write-Step "Would create directory $targetPath"
            } else {
                New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
            }
            $createdDirectories++
        }
        continue
    }

    $targetDirectory = Split-Path -Parent $targetPath
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
        Copy-Item -LiteralPath $item.FullName -Destination $targetPath -Force
    }
    $copiedFiles++
}

$marketplace = [ordered]@{
    name = "codex-review-local"
    interface = @{
        displayName = "Codex Review Local"
    }
    plugins = @(
        [ordered]@{
            name = $pluginName
            source = @{
                source = "local"
                path = "./plugins/$pluginName"
            }
            policy = @{
                installation = "AVAILABLE"
                authentication = "ON_INSTALL"
            }
            category = if ($pluginManifest.interface.category) { [string]$pluginManifest.interface.category } else { "Coding" }
        }
    )
}

$marketplaceJson = $marketplace | ConvertTo-Json -Depth 6

if ($DryRun) {
    Write-Step "Would write marketplace manifest $marketplaceJsonPath"
} else {
    Set-Content -LiteralPath $marketplaceJsonPath -Value $marketplaceJson -Encoding utf8
    Write-Step "Wrote marketplace manifest $marketplaceJsonPath"
}

$mode = if ($DryRun) { "dry-run" } else { "install" }
Write-Step "Completed plugin $mode from $resolvedSource to $pluginDestination"
Write-Step "Directories created: $createdDirectories"
Write-Step "Files processed: $copiedFiles"
Write-Step "Marketplace root: $resolvedMarketplaceRoot"
Write-Step "Restart Codex if the plugin does not appear immediately."
