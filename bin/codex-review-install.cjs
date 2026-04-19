#!/usr/bin/env node

// Keep the published bin entry on a tiny CommonJS wrapper so npm's Windows
// launch shims hand off to a simple Node file before the real ESM installer.
import("../scripts/install_plugin_to_codex.mjs");
