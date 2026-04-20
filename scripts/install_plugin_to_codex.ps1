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

function Write-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Value
    )

    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Value, $encoding)
}

function Clear-DirectoryContents {
    param(
        [string]$Path,
        [switch]$DryRunMode
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return
    }

    foreach ($child in Get-ChildItem -LiteralPath $Path -Force) {
        if ($DryRunMode) {
            Write-Step "Would remove stale path $($child.FullName)"
        } else {
            Remove-Item -LiteralPath $child.FullName -Recurse -Force
        }
    }
}

function Update-TomlBlock {
    param(
        [string]$Content,
        [string]$Header,
        [string]$Block
    )

    $normalized = $Content -replace "`r`n", "`n"
    $lines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in ($normalized -split "`n", 0, 'SimpleMatch')) {
        $lines.Add($line)
    }

    $startIndex = -1
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -eq $Header) {
            $startIndex = $index
            break
        }
    }

    $replacementLines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in (($Block -replace "`r`n", "`n").TrimEnd("`n") -split "`n", 0, 'SimpleMatch')) {
        $replacementLines.Add($line)
    }

    if ($startIndex -ge 0) {
        $endIndex = $startIndex + 1
        while ($endIndex -lt $lines.Count -and -not $lines[$endIndex].StartsWith("[")) {
            $endIndex++
        }
        $removeCount = $endIndex - $startIndex
        $lines.RemoveRange($startIndex, $removeCount)
        $lines.InsertRange($startIndex, $replacementLines)
    } else {
        while ($lines.Count -gt 0 -and [string]::IsNullOrWhiteSpace($lines[$lines.Count - 1])) {
            $lines.RemoveAt($lines.Count - 1)
        }
        if ($lines.Count -gt 0) {
            $lines.Add("")
        }
        foreach ($line in $replacementLines) {
            $lines.Add($line)
        }
    }

    return (($lines -join "`r`n").TrimEnd() + "`r`n")
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

        Write-Utf8NoBom -Path $ConfigPath -Value $block
        Write-Step "Created config file $ConfigPath with plugin enable block for $PluginRef"
        return
    }

    $content = Get-Content -LiteralPath $ConfigPath -Raw
    $updated = Update-TomlBlock -Content $content -Header $header -Block $block

    if ($updated -eq $content) {
        Write-Step "Plugin enable block already present in $ConfigPath"
        return
    }

    if ($DryRunMode) {
        Write-Step "Would enable plugin $PluginRef in $ConfigPath"
        return
    }

    Write-Utf8NoBom -Path $ConfigPath -Value $updated
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

        Write-Utf8NoBom -Path $ConfigPath -Value $block
        Write-Step "Created config file $ConfigPath with marketplace block for $MarketplaceName"
        return
    }

    $content = Get-Content -LiteralPath $ConfigPath -Raw
    $updated = Update-TomlBlock -Content $content -Header $header -Block $block

    if ($DryRunMode) {
        Write-Step "Would register marketplace $MarketplaceName in $ConfigPath"
        return
    }

    Write-Utf8NoBom -Path $ConfigPath -Value $updated
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
$pluginVersion = [string]$pluginManifest.version

if ([string]::IsNullOrWhiteSpace($pluginName)) {
    throw "Plugin manifest did not contain a plugin name."
}

if ([string]::IsNullOrWhiteSpace($pluginVersion)) {
    throw "Plugin manifest did not contain a plugin version."
}

$marketplaceRoot = Join-Path $resolvedCodexHome "local-marketplaces\$MarketplaceName"
$pluginsRoot = Join-Path $marketplaceRoot "plugins"
$pluginDestination = Join-Path $pluginsRoot $pluginName
$pluginCacheRoot = Join-Path $resolvedCodexHome "plugins\cache\$MarketplaceName"
$pluginCachePluginRoot = Join-Path $pluginCacheRoot $pluginName
$pluginCacheDestination = Join-Path $pluginCachePluginRoot $pluginVersion
$agentsPluginsRoot = Join-Path $marketplaceRoot ".agents\plugins"
$marketplaceJsonPath = Join-Path $agentsPluginsRoot "marketplace.json"
$configTomlPath = Join-Path $resolvedCodexHome "config.toml"
$pluginRef = "$pluginName@$MarketplaceName"

Ensure-Directory -Path $resolvedCodexHome -DryRunMode:$DryRun
Ensure-Directory -Path $marketplaceRoot -DryRunMode:$DryRun
Ensure-Directory -Path $pluginsRoot -DryRunMode:$DryRun
Ensure-Directory -Path $pluginCacheRoot -DryRunMode:$DryRun
Ensure-Directory -Path $pluginCachePluginRoot -DryRunMode:$DryRun
Ensure-Directory -Path $agentsPluginsRoot -DryRunMode:$DryRun
Clear-DirectoryContents -Path $pluginCachePluginRoot -DryRunMode:$DryRun
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
    Write-Utf8NoBom -Path $marketplaceJsonPath -Value $marketplaceJson
    $writtenMarketplace = Get-Content -LiteralPath $marketplaceJsonPath -Raw | ConvertFrom-Json
    $writtenPlugin = @($writtenMarketplace.plugins | Where-Object { [string]$_.name -eq $pluginName }) | Select-Object -First 1
    if (-not $writtenPlugin) {
        throw "Marketplace manifest verification failed: plugin entry for $pluginName was not written."
    }
    if ([string]$writtenPlugin.policy.installation -ne "AVAILABLE") {
        $writtenPlugin.policy.installation = "AVAILABLE"
        $rewrittenJson = $writtenMarketplace | ConvertTo-Json -Depth 6
        Write-Utf8NoBom -Path $marketplaceJsonPath -Value $rewrittenJson
    }
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
