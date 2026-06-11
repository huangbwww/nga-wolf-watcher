from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools" / "install-linux.sh"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "linux-installer-release.yml"


def test_linux_installer_exposes_one_command_install_contract() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert script.startswith("#!/usr/bin/env bash")
    assert "set -Eeuo pipefail" in script
    assert "NGAWOLF_REPO" in script
    assert "NGAWOLF_VERSION" in script
    assert "NGAWOLF_SOURCE_DIR" in script
    assert "/opt/ngawolf" in script
    assert "/etc/ngawolf" in script
    assert "/var/lib/ngawolf" in script
    assert "/usr/local/bin/ngawolf" in script
    assert "https://github.com/${REPO}/releases/latest" in script
    assert "archive/refs/tags/${resolved_version}.tar.gz" in script


def test_linux_installer_generates_wrapper_and_systemd_service() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert 'source "${CONFIG_DIR}/install.env"' in script
    assert 'exec "\\$PYTHON_BIN" "\\$APP_DIR/ngawolf_cli.py"' in script
    assert '--config "\\$CONFIG_DIR/config.json"' in script
    assert '--data-dir "\\$DATA_DIR"' in script
    assert 'SERVICE_NAME="${NGAWOLF_SERVICE_NAME:-ngawolf}"' in script
    assert "ExecStart=${BIN_PATH} run" in script
    assert "Restart=on-failure" in script
    assert "WantedBy=multi-user.target" in script


def test_linux_installer_uses_headless_requirements_when_available() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "requirements-linux.txt" in script
    assert "python3 -m venv" in script
    assert 'install -r "$req_file"' in script


def test_release_workflow_uploads_installer_asset() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "types: [published]" in workflow
    assert "contents: write" in workflow
    assert "tools/install-linux.sh#install-linux.sh" in workflow
    assert "gh release upload" in workflow
