import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_NAME = "codex-review"


def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def require_file(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"Missing expected file: {path}")


def require_text(path: Path, expected: str) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if expected not in text:
        raise SystemExit(f"Expected {expected!r} in {path}")


def resolve_powershell() -> str:
    for candidate in ("pwsh", "powershell"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise SystemExit("PowerShell is required for the release smoke test. Install `pwsh` or `powershell` and retry.")


def verify_install_tree(codex_home: Path, marketplace_name: str) -> None:
    marketplace_root = codex_home / "local-marketplaces" / marketplace_name
    plugin_root = marketplace_root / "plugins" / PLUGIN_NAME
    plugin_manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    require_file(plugin_manifest_path)
    plugin_manifest = json.loads(plugin_manifest_path.read_text(encoding="utf-8"))
    plugin_version = plugin_manifest.get("version")
    if not plugin_version:
        raise SystemExit(f"Installed plugin manifest did not include a version at {plugin_root}")
    cache_plugin_root = codex_home / "plugins" / "cache" / marketplace_name / PLUGIN_NAME
    cache_root = cache_plugin_root / plugin_version
    marketplace_manifest = marketplace_root / ".agents" / "plugins" / "marketplace.json"
    config_toml = codex_home / "config.toml"

    for path in [plugin_root, cache_root]:
        if not path.is_dir():
            raise SystemExit(f"Missing installed plugin directory: {path}")

    require_file(plugin_root / ".codex-plugin" / "plugin.json")
    require_file(plugin_root / ".mcp.json")
    require_file(cache_root / ".codex-plugin" / "plugin.json")
    require_file(cache_root / ".mcp.json")
    require_file(marketplace_manifest)
    require_file(config_toml)

    legacy_cache_manifest = cache_plugin_root / ".codex-plugin" / "plugin.json"
    if legacy_cache_manifest.exists():
        raise SystemExit(
            f"Legacy flat cache layout is still present for {PLUGIN_NAME}: {legacy_cache_manifest.parent.parent}"
        )

    manifest = json.loads(marketplace_manifest.read_text(encoding="utf-8"))
    plugin_names = [plugin.get("name") for plugin in manifest.get("plugins", [])]
    if PLUGIN_NAME not in plugin_names:
        raise SystemExit(f"Marketplace manifest did not include {PLUGIN_NAME}")
    plugin_entries = [plugin for plugin in manifest.get("plugins", []) if plugin.get("name") == PLUGIN_NAME]
    installation_policy = plugin_entries[0].get("policy", {}).get("installation") if plugin_entries else None
    if installation_policy != "AVAILABLE":
        raise SystemExit(
            f"Marketplace manifest must keep installation policy AVAILABLE for {PLUGIN_NAME}, found {installation_policy!r}"
        )

    require_text(config_toml, f'[marketplaces.{marketplace_name}]')
    require_text(config_toml, f'[plugins."{PLUGIN_NAME}@{marketplace_name}"]')


def run_powershell_install_smoke(temp_root: Path) -> None:
    codex_home = temp_root / "ps-codex-home"
    marketplace_name = "codex-review-ps-test"
    run_cmd(
        [
            resolve_powershell(),
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "install_plugin_to_codex.ps1"),
            "-CodexHome",
            str(codex_home),
            "-MarketplaceName",
            marketplace_name,
        ],
        REPO_ROOT,
    )
    verify_install_tree(codex_home, marketplace_name)


def run_node_install_smoke(temp_root: Path) -> None:
    codex_home = temp_root / "node-codex-home"
    marketplace_name = "codex-review-node-test"
    run_cmd(
        [
            "node",
            str(REPO_ROOT / "scripts" / "install_plugin_to_codex.mjs"),
            "--codex-home",
            str(codex_home),
            "--marketplace-name",
            marketplace_name,
        ],
        REPO_ROOT,
    )
    verify_install_tree(codex_home, marketplace_name)


def run_release_bundle_smoke(temp_root: Path) -> None:
    output_root = temp_root / "release-output"
    run_cmd(
        [
            resolve_powershell(),
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "build_plugin_release_bundle.ps1"),
            "-OutputRoot",
            str(output_root),
        ],
        REPO_ROOT,
    )

    zip_files = sorted(output_root.glob("codex-review-*.zip"))
    tgz_files = sorted(output_root.glob("reviewpilot-codex-review-install-*.tgz"))
    if not zip_files:
        raise SystemExit("Release bundle smoke test did not produce a zip archive")
    if not tgz_files:
        raise SystemExit("Release bundle smoke test did not produce an npm tarball")

    bundle_root_dirs = [path for path in output_root.iterdir() if path.is_dir() and path.name.startswith("codex-review-")]
    if not bundle_root_dirs:
        raise SystemExit("Release bundle smoke test did not produce an expanded bundle folder")

    bundle_root = bundle_root_dirs[0]
    require_file(bundle_root / "README-INSTALL.md")
    require_file(bundle_root / "LICENSE")
    require_file(bundle_root / "plugins" / PLUGIN_NAME / ".mcp.json")

    with zipfile.ZipFile(zip_files[0]) as archive:
        archive_names = set(archive.namelist())
        expected_members = {
            "README-INSTALL.md",
            "LICENSE",
            f"plugins/{PLUGIN_NAME}/.mcp.json",
            f"plugins/{PLUGIN_NAME}/.codex-plugin/plugin.json",
            "scripts/install_plugin_to_codex.ps1",
            "scripts/install_plugin_to_codex.mjs",
        }
        missing = [member for member in expected_members if member not in archive_names]
        if missing:
            raise SystemExit(f"Release zip is missing expected files: {missing}")


def main() -> int:
    validator = REPO_ROOT / "scripts" / "validate_public_release.py"
    run_cmd([sys.executable, str(validator)], REPO_ROOT)

    with tempfile.TemporaryDirectory(prefix="codex-review-release-smoke-") as temp_dir:
        temp_root = Path(temp_dir)
        run_powershell_install_smoke(temp_root)
        run_node_install_smoke(temp_root)
        run_release_bundle_smoke(temp_root)

    print("Release smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
