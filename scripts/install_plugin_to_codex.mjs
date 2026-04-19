#!/usr/bin/env node

import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

function logStep(message) {
  process.stdout.write(`[install-plugin] ${message}\n`);
}

function parseArgs(argv) {
  const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
  const options = {
    source: path.resolve(scriptDirectory, "../plugins/codex-review"),
    codexHome: path.join(os.homedir(), ".codex"),
    marketplaceName: "codex-review-local",
    includePycache: false,
    dryRun: false,
  };

  function requireValue(flagName, index) {
    const nextArg = argv[index + 1];
    if (!nextArg || nextArg.startsWith("--")) {
      throw new Error(`${flagName} requires a value`);
    }
    return nextArg;
  }

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--dry-run") {
      options.dryRun = true;
      continue;
    }
    if (arg === "--include-pycache") {
      options.includePycache = true;
      continue;
    }
    if (arg === "--source") {
      const nextArg = requireValue("--source", index);
      index += 1;
      options.source = path.resolve(nextArg);
      continue;
    }
    if (arg === "--codex-home") {
      const nextArg = requireValue("--codex-home", index);
      index += 1;
      options.codexHome = path.resolve(nextArg);
      continue;
    }
    if (arg === "--marketplace-name") {
      const nextArg = requireValue("--marketplace-name", index);
      index += 1;
      options.marketplaceName = nextArg;
      continue;
    }
    throw new Error(`Unknown argument: ${arg}`);
  }

  return options;
}

async function pathExists(targetPath) {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

function shouldSkipPath(targetPath, includePycache) {
  return !includePycache && targetPath.split(/[\\/]/).includes("__pycache__");
}

async function ensureDirectory(targetPath, dryRun) {
  if (await pathExists(targetPath)) {
    return;
  }
  if (dryRun) {
    logStep(`Would create directory ${targetPath}`);
    return;
  }
  await fs.mkdir(targetPath, { recursive: true });
  logStep(`Created directory ${targetPath}`);
}

async function copyTree(sourceRoot, destinationRoot, options) {
  const entries = await fs.readdir(sourceRoot, { withFileTypes: true });

  for (const entry of entries) {
    const sourcePath = path.join(sourceRoot, entry.name);
    if (shouldSkipPath(sourcePath, options.includePycache)) {
      continue;
    }

    const destinationPath = path.join(destinationRoot, entry.name);

    if (entry.isDirectory()) {
      if (options.dryRun) {
        logStep(`Would create directory ${destinationPath}`);
      } else {
        await fs.mkdir(destinationPath, { recursive: true });
      }
      await copyTree(sourcePath, destinationPath, options);
      continue;
    }

    if (options.dryRun) {
      logStep(`Would copy ${sourcePath} -> ${destinationPath}`);
      continue;
    }

    await fs.mkdir(path.dirname(destinationPath), { recursive: true });
    await fs.copyFile(sourcePath, destinationPath);
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const pluginManifestPath = path.join(options.source, ".codex-plugin", "plugin.json");

  if (!(await pathExists(pluginManifestPath))) {
    throw new Error(`Plugin manifest not found: ${pluginManifestPath}`);
  }

  const pluginManifest = JSON.parse(await fs.readFile(pluginManifestPath, "utf8"));
  const pluginName = String(pluginManifest.name || "").trim();
  if (!pluginName) {
    throw new Error("Plugin manifest did not contain a plugin name.");
  }

  const marketplaceRoot = path.join(options.codexHome, "local-marketplaces", options.marketplaceName);
  const pluginsRoot = path.join(marketplaceRoot, "plugins");
  const pluginDestination = path.join(pluginsRoot, pluginName);
  const pluginCacheRoot = path.join(options.codexHome, "plugins", "cache", options.marketplaceName);
  const pluginCacheDestination = path.join(pluginCacheRoot, pluginName);
  const agentsPluginsRoot = path.join(marketplaceRoot, ".agents", "plugins");
  const marketplaceJsonPath = path.join(agentsPluginsRoot, "marketplace.json");

  await ensureDirectory(options.codexHome, options.dryRun);
  await ensureDirectory(marketplaceRoot, options.dryRun);
  await ensureDirectory(pluginsRoot, options.dryRun);
  await ensureDirectory(pluginCacheRoot, options.dryRun);
  await ensureDirectory(agentsPluginsRoot, options.dryRun);
  await ensureDirectory(pluginDestination, options.dryRun);
  await ensureDirectory(pluginCacheDestination, options.dryRun);

  await copyTree(options.source, pluginDestination, options);
  await copyTree(options.source, pluginCacheDestination, options);

  const marketplace = {
    name: options.marketplaceName,
    interface: {
      displayName: "Codex Review Local",
    },
    plugins: [
      {
        name: pluginName,
        source: {
          source: "local",
          path: `./plugins/${pluginName}`,
        },
        policy: {
          installation: "AVAILABLE",
          authentication: "ON_INSTALL",
        },
        category: String(pluginManifest?.interface?.category || "Coding"),
      },
    ],
  };

  if (options.dryRun) {
    logStep(`Would write marketplace manifest ${marketplaceJsonPath}`);
  } else {
    await fs.writeFile(marketplaceJsonPath, `${JSON.stringify(marketplace, null, 2)}\n`, "utf8");
    logStep(`Wrote marketplace manifest ${marketplaceJsonPath}`);
  }

  logStep(`Completed plugin ${options.dryRun ? "dry-run" : "install"} from ${options.source} to ${pluginDestination}`);
  logStep(`Codex home: ${options.codexHome}`);
  logStep(`Marketplace root: ${marketplaceRoot}`);
  logStep(`Plugin path: ${pluginDestination}`);
  logStep(`Plugin cache path: ${pluginCacheDestination}`);
  logStep(`Marketplace file: ${marketplaceJsonPath}`);
  logStep("Restart Codex Desktop if the plugin does not appear immediately.");
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
