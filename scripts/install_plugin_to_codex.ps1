param(
    [string]$Source = (Join-Path $PSScriptRoot "..\plugins\codex-review"),
    [string]$MarketplaceName = "codex-review-local",
    [string]$CodexHome = (Join-Path $HOME ".codex"),
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

function Copy-PluginTree {
    param(
        [string]$SourceRoot,
        [string]$DestinationRoot,
        [switch]$DryRunMode
    )

    if (-not (Test-Path -LiteralPath $DestinationRoot -PathType Container)) {
        if ($DryRunMode) {
            Write-Step "Would create plugin destination $DestinationRoot"
        } else {
            New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
            Write-Step "Created plugin destination $DestinationRoot"
        }
    }

    $sourceFiles = Get-ChildItem -LiteralPath $SourceRoot -Recurse -Force |
        Where-Object { -not (Should-SkipPath $_.FullName) }
    $copiedFiles = 0
    $createdDirectories = 0

    foreach ($item in $sourceFiles) {
        $relativePath = $item.FullName.Substring($SourceRoot.Length).TrimStart('\', '/')
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            continue
        }

        $targetPath = Join-Path $DestinationRoot $relativePath

        if ($item.PSIsContainer) {
            if (-not (Test-Path -LiteralPath $targetPath -PathType Container)) {
                if ($DryRunMode) {
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
            if ($DryRunMode) {
                Write-Step "Would create directory $targetDirectory"
            } else {
                New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
            }
            $createdDirectories++
        }

        if ($DryRunMode) {
            Write-Step "Would copy $relativePath to $DestinationRoot"
        } else {
            Copy-Item -LiteralPath $item.FullName -Destination $targetPath -Force
        }
        $copiedFiles++
    }

    return [pscustomobject]@{
        CreatedDirectories = $createdDirectories
        CopiedFiles = $copiedFiles
    }
}

function Update-PluginConfig {
    param(
        [string]$ConfigPath,
        [string]$PluginRef,
        [switch]$DryRunMode
    )

    $header = "[plugins.`"$PluginRef`"]"
    $enabledLine = "enabled = true"
    $block = "$header`r`n$enabledLine`r`n"

    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        if ($DryRunMode) {
            Write-Step "Would create config file $ConfigPath with plugin enable block for $PluginRef"
            return
        }

        Set-Content -LiteralPath $ConfigPath -Value $block -Encoding utf8
        Write-Step "Created config file $ConfigPath with plugin enable block for $PluginRef"
        return
    }

    $content = Get-Content -LiteralPath $ConfigPath -Raw
    $escapedRef = [regex]::Escape($PluginRef)
    $blockPattern = "(?ms)^\[plugins\.`"$escapedRef`"\]\r?\n(?:.+\r?\n)*?(?=^\[|^\[\[|\z)"
    $enabledPattern = "(?ms)^\[plugins\.`"$escapedRef`"\]\r?\n(?:.+\r?\n)*?^enabled\s*=\s*true\s*$"

    if ($content -match $enabledPattern) {
        Write-Step "Plugin enable block already present in $ConfigPath"
        return
    }

    $updated = if ($content -match $blockPattern) {
        [regex]::Replace($content, $blockPattern, $block)
    } else {
        $separator = if ($content.EndsWith("`n") -or $content.Length -eq 0) { "" } else { "`r`n" }
        $content + $separator + "`r`n" + $block
    }

    if ($DryRunMode) {
        Write-Step "Would enable plugin $PluginRef in $ConfigPath"
        return
    }

    Set-Content -LiteralPath $ConfigPath -Value $updated -Encoding utf8
    Write-Step "Enabled plugin $PluginRef in $ConfigPath"
}

function Update-MarketplaceConfig {
    param(
        [string]$ConfigPath,
        [string]$MarketplaceName,
        [string]$MarketplaceRoot,
        [switch]$DryRunMode
    )

    $timestamp = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    $sourceValue = if ($MarketplaceRoot -match '^[A-Za-z]:\\') {
        "\\?\$MarketplaceRoot"
    } else {
        $MarketplaceRoot
    }
    $header = "[marketplaces.$MarketplaceName]"
    $block = "$header`r`nlast_updated = `"$timestamp`"`r`nsource_type = `"local`"`r`nsource = '$sourceValue'`r`n"

    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        if ($DryRunMode) {
            Write-Step "Would create config file $ConfigPath with marketplace block for $MarketplaceName"
            return
        }

        Set-Content -LiteralPath $ConfigPath -Value $block -Encoding utf8
        Write-Step "Created config file $ConfigPath with marketplace block for $MarketplaceName"
        return
    }

    $content = Get-Content -LiteralPath $ConfigPath -Raw
    $escapedName = [regex]::Escape($MarketplaceName)
    $blockPattern = "(?ms)^\[marketplaces\.$escapedName\]\r?\n(?:.+\r?\n)*?(?=^\[|^\[\[|\z)"
    $existingSourcePattern = "(?ms)^\[marketplaces\.$escapedName\]\r?\n(?:.+\r?\n)*?^source\s*=\s*`"$([regex]::Escape($sourceValue))`"\s*$"

    if ($content -match $existingSourcePattern) {
        $updated = [regex]::Replace($content, $blockPattern, $block)
    } elseif ($content -match $blockPattern) {
        $updated = [regex]::Replace($content, $blockPattern, $block)
    } else {
        $separator = if ($content.EndsWith("`n") -or $content.Length -eq 0) { "" } else { "`r`n" }
        $updated = $content + $separator + "`r`n" + $block
    }

    if ($DryRunMode) {
        Write-Step "Would register marketplace $MarketplaceName in $ConfigPath"
        return
    }

    Set-Content -LiteralPath $ConfigPath -Value $updated -Encoding utf8
    Write-Step "Registered marketplace $MarketplaceName in $ConfigPath"
}

function Should-SkipPath {
    param([string]$Path)

    if ($IncludePycache) {
        return $false
    }

    return $Path -split '[\\/]' -contains "__pycache__"
}

$resolvedSource = (Resolve-Path -LiteralPath $Source).Path
$resolvedCodexHome = if ([System.IO.Path]::IsPathRooted($CodexHome)) {
    [System.IO.Path]::GetFullPath($CodexHome)
} else {
    [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $CodexHome))
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

$marketplaceRoot = Join-Path $resolvedCodexHome "local-marketplaces\$MarketplaceName"
$pluginsRoot = Join-Path $marketplaceRoot "plugins"
$pluginDestination = Join-Path $pluginsRoot $pluginName
$pluginCacheRoot = Join-Path $resolvedCodexHome "plugins\cache\$MarketplaceName"
$pluginCacheDestination = Join-Path $pluginCacheRoot $pluginName
$agentsPluginsRoot = Join-Path $marketplaceRoot ".agents\plugins"
$marketplaceJsonPath = Join-Path $agentsPluginsRoot "marketplace.json"
$configTomlPath = Join-Path $resolvedCodexHome "config.toml"
$pluginRef = "$pluginName@$MarketplaceName"

Ensure-Directory -Path $resolvedCodexHome -DryRunMode:$DryRun
Ensure-Directory -Path $marketplaceRoot -DryRunMode:$DryRun
Ensure-Directory -Path $pluginsRoot -DryRunMode:$DryRun
Ensure-Directory -Path $pluginCacheRoot -DryRunMode:$DryRun
Ensure-Directory -Path $agentsPluginsRoot -DryRunMode:$DryRun
$marketplaceCopy = Copy-PluginTree -SourceRoot $resolvedSource -DestinationRoot $pluginDestination -DryRunMode:$DryRun
$cacheCopy = Copy-PluginTree -SourceRoot $resolvedSource -DestinationRoot $pluginCacheDestination -DryRunMode:$DryRun

$pluginEntry = [ordered]@{
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

$marketplace = if (Test-Path -LiteralPath $marketplaceJsonPath -PathType Leaf) {
    Get-Content -LiteralPath $marketplaceJsonPath -Raw | ConvertFrom-Json
} else {
    [pscustomobject]@{
        name = $MarketplaceName
        interface = @{
            displayName = "Codex Review Local"
        }
        plugins = @()
    }
}

$existingPlugins = @()
if ($marketplace.plugins) {
    $existingPlugins = @($marketplace.plugins | Where-Object { [string]$_.name -ne $pluginName })
}

$marketplace = [ordered]@{
    name = if ($marketplace.name) { [string]$marketplace.name } else { $MarketplaceName }
    interface = if ($marketplace.interface) { $marketplace.interface } else { @{ displayName = "Codex Review Local" } }
    plugins = @($existingPlugins + $pluginEntry)
}

$marketplaceJson = $marketplace | ConvertTo-Json -Depth 6

if ($DryRun) {
    Write-Step "Would write marketplace manifest $marketplaceJsonPath"
} else {
    Set-Content -LiteralPath $marketplaceJsonPath -Value $marketplaceJson -Encoding utf8
    Write-Step "Wrote marketplace manifest $marketplaceJsonPath"
}

Update-MarketplaceConfig -ConfigPath $configTomlPath -MarketplaceName $MarketplaceName -MarketplaceRoot $marketplaceRoot -DryRunMode:$DryRun
Update-PluginConfig -ConfigPath $configTomlPath -PluginRef $pluginRef -DryRunMode:$DryRun

$mode = if ($DryRun) { "dry-run" } else { "install" }
Write-Step "Completed plugin $mode from $resolvedSource to $pluginDestination"
Write-Step "Marketplace directories created: $($marketplaceCopy.CreatedDirectories)"
Write-Step "Marketplace files processed: $($marketplaceCopy.CopiedFiles)"
Write-Step "Cache directories created: $($cacheCopy.CreatedDirectories)"
Write-Step "Cache files processed: $($cacheCopy.CopiedFiles)"
Write-Step "Codex home: $resolvedCodexHome"
Write-Step "Marketplace root: $marketplaceRoot"
Write-Step "Plugin path: $pluginDestination"
Write-Step "Plugin cache path: $pluginCacheDestination"
Write-Step "Marketplace file: $marketplaceJsonPath"
Write-Step "Config file: $configTomlPath"
Write-Step "Restart Codex Desktop if the plugin does not appear immediately."
