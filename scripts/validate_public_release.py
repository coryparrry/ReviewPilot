import json
import py_compile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_JSON = REPO_ROOT / "package.json"
PLUGIN_JSON = REPO_ROOT / "plugins" / "codex-review" / ".codex-plugin" / "plugin.json"
PLUGIN_MCP_JSON = REPO_ROOT / "plugins" / "codex-review" / ".mcp.json"
LICENSE_FILE = REPO_ROOT / "LICENSE"
README_FILE = REPO_ROOT / "README.md"
GITHUB_MCP_SETUP_DOC = REPO_ROOT / "docs" / "github-mcp-setup.md"


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc


def require_file(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"Missing required file: {path}")


def validate_metadata() -> None:
    package_data = load_json(PACKAGE_JSON)
    plugin_data = load_json(PLUGIN_JSON)

    package_license = package_data.get("license")
    plugin_license = plugin_data.get("license")

    if package_license != "MIT":
        raise SystemExit(
            f"package.json license must be MIT, found: {package_license!r}"
        )
    if plugin_license != "MIT":
        raise SystemExit(f"plugin.json license must be MIT, found: {plugin_license!r}")

    package_files = package_data.get("files", [])
    if "LICENSE" not in package_files:
        raise SystemExit("package.json files list must include LICENSE")

    expected_repo_url = "https://github.com/coryparrry/ReviewPilot"
    expected_repo_git_url = "git+https://github.com/coryparrry/ReviewPilot.git"

    if package_data.get("homepage") != expected_repo_url:
        raise SystemExit("package.json homepage must point at the public GitHub repo")
    repository = package_data.get("repository", {})
    if repository.get("url") != expected_repo_git_url:
        raise SystemExit(
            "package.json repository.url must point at the public GitHub git URL"
        )
    bugs = package_data.get("bugs", {})
    if bugs.get("url") != f"{expected_repo_url}/issues":
        raise SystemExit(
            "package.json bugs.url must point at the public GitHub issues URL"
        )

    plugin_interface = plugin_data.get("interface", {})
    if not plugin_interface.get("displayName"):
        raise SystemExit("plugin.json interface.displayName is required")
    if not plugin_interface.get("shortDescription"):
        raise SystemExit("plugin.json interface.shortDescription is required")
    if plugin_data.get("homepage") != expected_repo_url:
        raise SystemExit("plugin.json homepage must point at the public GitHub repo")
    if plugin_data.get("repository") != expected_repo_url:
        raise SystemExit("plugin.json repository must point at the public GitHub repo")
    if plugin_interface.get("websiteURL") != expected_repo_url:
        raise SystemExit(
            "plugin.json interface.websiteURL must point at the public GitHub repo"
        )


def validate_readme() -> None:
    text = README_FILE.read_text(encoding="utf-8", errors="replace")
    required_phrases = [
        "ReviewPilot",
        "Install",
        "Quick Start",
        "GitHub MCP setup",
        "Publish Readiness",
        "validate_public_release.py",
    ]
    for phrase in required_phrases:
        if phrase not in text:
            raise SystemExit(f"README.md is missing expected text: {phrase!r}")


def validate_python_scripts() -> None:
    script_roots = [
        REPO_ROOT / "scripts",
        REPO_ROOT / "plugins" / "codex-review" / "scripts",
        REPO_ROOT
        / "plugins"
        / "codex-review"
        / "skills"
        / "bug-hunting-code-review"
        / "scripts",
    ]
    for root in script_roots:
        for path in root.glob("*.py"):
            py_compile.compile(str(path), doraise=True)


def validate_mcp_config() -> None:
    config = load_json(PLUGIN_MCP_JSON)
    github = config.get("github", {})
    if github.get("type") != "http":
        raise SystemExit("plugins/codex-review/.mcp.json github.type must be 'http'")
    if github.get("url") != "https://api.githubcopilot.com/mcp/":
        raise SystemExit(
            "plugins/codex-review/.mcp.json github.url must point at the GitHub MCP endpoint"
        )

    headers = github.get("headers", {})
    if headers.get("X-MCP-Readonly") != "true":
        raise SystemExit(
            "plugins/codex-review/.mcp.json must keep GitHub MCP read-only"
        )
    if headers.get("X-MCP-Toolsets") != "pull_requests":
        raise SystemExit(
            "plugins/codex-review/.mcp.json must limit the GitHub MCP toolset to pull_requests"
        )


def main() -> int:
    for path in [
        PACKAGE_JSON,
        PLUGIN_JSON,
        PLUGIN_MCP_JSON,
        LICENSE_FILE,
        README_FILE,
        GITHUB_MCP_SETUP_DOC,
    ]:
        require_file(path)

    validate_metadata()
    validate_readme()
    validate_mcp_config()
    validate_python_scripts()

    print("Public release validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
