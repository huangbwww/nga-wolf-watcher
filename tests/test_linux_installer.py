from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools" / "install-linux.sh"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CLI_SPEC = ROOT / "NGA-Wolf-Watcher-CLI.spec"
WINDOWS_ONEDIR_SPEC = ROOT / "NGA-Wolf-Watcher-Web-Onedir.spec"
WINDOWS_INSTALLER_SPEC = ROOT / "packaging" / "windows" / "nga-wolf-watcher.iss"


def test_linux_installer_exposes_one_command_install_contract() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert script.startswith("#!/usr/bin/env bash")
    assert "set -Eeuo pipefail" in script
    assert "NGAWOLF_REPO" in script
    assert "NGAWOLF_VERSION" in script
    assert "NGAWOLF_SOURCE_DIR" in script
    assert "NGAWOLF_INSTALL_FROM_SOURCE" in script
    assert "NGAWOLF_PACKAGE_URL" in script
    assert "NGAWOLF_CHECKSUMS_URL" in script
    assert "/opt/ngawolf" in script
    assert "/etc/ngawolf" in script
    assert "/var/lib/ngawolf" in script
    assert "/usr/local/bin/ngawolf" in script
    assert "https://github.com/${REPO}/releases/latest" in script
    assert "archive/refs/tags/${resolved_version}.tar.gz" in script


def test_linux_installer_generates_wrapper_and_systemd_service() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert 'source "${CONFIG_DIR}/install.env"' in script
    assert 'if [[ -n "\\${APP_EXEC:-}" && -x "\\$APP_EXEC" ]]; then' in script
    assert 'exec "\\$APP_EXEC"' in script
    assert 'exec "\\$PYTHON_BIN" "\\$APP_DIR/ngawolf_cli.py"' in script
    assert '--config "\\$CONFIG_DIR/config.json"' in script
    assert '--data-dir "\\$DATA_DIR"' in script
    assert 'SERVICE_NAME="${NGAWOLF_SERVICE_NAME:-ngawolf}"' in script
    assert "ExecStart=${BIN_PATH} run" in script
    assert "Restart=on-failure" in script
    assert "StandardOutput=append:${LOG_DIR}/watcher.log" in script
    assert "StandardError=append:${LOG_DIR}/watcher.log" in script
    assert "WantedBy=multi-user.target" in script


def test_linux_installer_uses_headless_requirements_when_available() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "requirements-linux.txt" in script
    assert "python3 -m venv" in script
    assert 'install -r "$req_file"' in script
    assert 'if [[ "$INSTALL_KIND" == "source" ]]; then' in script


def test_linux_installer_supports_github_proxy_and_custom_archive_url() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "NGAWOLF_GITHUB_PROXY" in script
    assert "NGAWOLF_ARCHIVE_URL" in script
    assert "github_url()" in script
    assert '"${GITHUB_PROXY%/}/$url"' in script
    assert 'github_url "https://github.com/${REPO}/releases/latest"' in script
    assert 'github_url "https://github.com/${REPO}/archive/refs/tags/${resolved_version}.tar.gz"' in script
    assert 'archive_url="$ARCHIVE_URL"' in script


def test_linux_installer_prefers_standard_release_package() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "detect_package_arch()" in script
    assert "download_release_package()" in script
    assert "install_binary_package()" in script
    assert "verify_package_checksum()" in script
    assert 'nga-wolf-watcher-${resolved_version}-linux-${package_arch}.tar.gz' in script
    assert 'github_url "https://github.com/${REPO}/releases/download/${resolved_version}/${asset_name}"' in script
    assert 'github_url "https://github.com/${REPO}/releases/download/${resolved_version}/SHA256SUMS"' in script
    assert '$2 == name' in script
    assert "sha256sum -c" in script
    assert '[[ -x "${next_app}/ngawolf" ]]' in script
    assert 'INSTALL_KIND="binary"' in script


def test_linux_installer_prints_background_management_commands() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "sudo ngawolf start" in script
    assert "sudo ngawolf stop" in script
    assert "sudo ngawolf status" in script
    assert "sudo ngawolf logs -f" in script


def test_release_workflow_builds_standard_assets() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "tags:" in workflow
    assert "'v*'" in workflow
    assert "contents: write" in workflow
    assert "ubuntu-22.04" in workflow
    assert "ubuntu-22.04-arm" in workflow
    assert "windows-2025" in workflow
    assert "nga-wolf-watcher-${TAG}-linux-${ARCH}.tar.gz" in workflow
    assert "nga-wolf-watcher-${TAG}-windows-x86_64-portable.zip" in workflow
    assert "nga-wolf-watcher-${TAG}-windows-x86_64-setup.exe" in workflow
    assert "SHA256SUMS" in workflow
    assert "gh release upload" in workflow
    assert "release-assets/install-linux.sh" in workflow


def test_release_packaging_specs_exist_and_use_standard_shapes() -> None:
    cli_spec = CLI_SPEC.read_text(encoding="utf-8")
    windows_spec = WINDOWS_ONEDIR_SPEC.read_text(encoding="utf-8")
    installer_spec = WINDOWS_INSTALLER_SPEC.read_text(encoding="utf-8")

    assert "COLLECT(" in cli_spec
    assert "name='ngawolf'" in cli_spec
    assert "console=True" in cli_spec
    assert "COLLECT(" in windows_spec
    assert "name='NGA-Wolf-Watcher'" in windows_spec
    assert "console=False" in windows_spec
    assert "#define AppVersion" in installer_spec
    assert "DefaultDirName={localappdata}\\Programs\\NGA Wolf Watcher" in installer_spec
    assert "ArchitecturesAllowed=x64compatible" in installer_spec
    assert "UninstallDisplayIcon={app}\\NGA-Wolf-Watcher.exe" in installer_spec
