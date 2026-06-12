#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${NGAWOLF_REPO:-huangbwww/nga-wolf-watcher}"
VERSION="${NGAWOLF_VERSION:-latest}"
SOURCE_DIR="${NGAWOLF_SOURCE_DIR:-}"
INSTALL_DIR="${NGAWOLF_INSTALL_DIR:-/opt/ngawolf}"
APP_DIR="${INSTALL_DIR}/app"
VENV_DIR="${INSTALL_DIR}/venv"
BIN_PATH="${NGAWOLF_BIN_PATH:-/usr/local/bin/ngawolf}"
CONFIG_DIR="${NGAWOLF_CONFIG_DIR:-/etc/ngawolf}"
DATA_DIR="${NGAWOLF_DATA_DIR:-/var/lib/ngawolf}"
LOG_DIR="${NGAWOLF_LOG_DIR:-/var/log/ngawolf}"
SERVICE_NAME="${NGAWOLF_SERVICE_NAME:-ngawolf}"
INSTALL_SYSTEMD="${NGAWOLF_INSTALL_SYSTEMD:-1}"
INSTALL_OS_DEPS="${NGAWOLF_INSTALL_OS_DEPS:-1}"

TMP_DIR=""

log() {
  printf '[ngawolf] %s\n' "$*"
}

die() {
  printf '[ngawolf] ERROR: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

require_root() {
  if [[ "$(id -u)" != "0" ]]; then
    die "Please run as root, for example: curl -fsSL https://github.com/${REPO}/releases/latest/download/install-linux.sh | sudo bash"
  fi
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

install_os_dependencies() {
  if [[ "$INSTALL_OS_DEPS" == "0" ]]; then
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y python3 python3-venv python3-pip curl ca-certificates tar
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip curl ca-certificates tar
    return
  fi

  if command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-pip curl ca-certificates tar
    return
  fi

  if command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive install python3 python3-pip curl ca-certificates tar
    return
  fi

  if command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm --needed python python-pip curl ca-certificates tar
    return
  fi

  log "No supported package manager detected; assuming Python, curl, and tar are already installed."
}

resolve_latest_version() {
  local latest_url
  latest_url="$(curl -fsSIL -o /dev/null -w '%{url_effective}' "https://github.com/${REPO}/releases/latest")"
  [[ "$latest_url" != */tag/* ]] && die "Could not resolve latest release for ${REPO}"
  printf '%s\n' "${latest_url##*/}"
}

download_release_source() {
  local resolved_version="$1"
  local archive_path="$2"
  local archive_url="https://github.com/${REPO}/archive/refs/tags/${resolved_version}.tar.gz"

  log "Downloading ${REPO} ${resolved_version}"
  curl -fL "$archive_url" -o "$archive_path"
}

copy_source_dir() {
  local source="$1"
  local target="$2"

  [[ -f "${source}/ngawolf_cli.py" ]] || die "NGAWOLF_SOURCE_DIR does not look like an NGA Wolf source directory: ${source}"
  mkdir -p "$target"
  (
    cd "$source"
    tar \
      --exclude .git \
      --exclude .venv \
      --exclude .tmp \
      --exclude .pytest_cache \
      --exclude __pycache__ \
      -cf - .
  ) | (
    cd "$target"
    tar -xf -
  )
}

install_application_files() {
  TMP_DIR="$(mktemp -d)"
  local next_app="${INSTALL_DIR}/app.new"
  rm -rf "$next_app"
  mkdir -p "$INSTALL_DIR" "$next_app"

  if [[ -n "$SOURCE_DIR" ]]; then
    log "Installing from local source: ${SOURCE_DIR}"
    copy_source_dir "$SOURCE_DIR" "$next_app"
  else
    local resolved_version="$VERSION"
    if [[ "$resolved_version" == "latest" ]]; then
      resolved_version="$(resolve_latest_version)"
    fi
    local archive_path="${TMP_DIR}/ngawolf.tar.gz"
    download_release_source "$resolved_version" "$archive_path"
    tar -xzf "$archive_path" -C "$next_app" --strip-components=1
  fi

  [[ -f "${next_app}/ngawolf_cli.py" ]] || die "Downloaded archive does not contain ngawolf_cli.py"
  rm -rf "$APP_DIR"
  mv "$next_app" "$APP_DIR"
}

install_python_environment() {
  need_command python3
  log "Creating Python virtual environment"
  python3 -m venv "$VENV_DIR"

  local pip_bin="${VENV_DIR}/bin/pip"
  local req_file="${APP_DIR}/requirements-linux.txt"
  if [[ ! -f "$req_file" ]]; then
    req_file="${APP_DIR}/requirements.txt"
  fi

  "$pip_bin" install --upgrade pip setuptools wheel
  "$pip_bin" install -r "$req_file"
}

write_install_env() {
  mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"
  cat > "${CONFIG_DIR}/install.env" <<EOF
APP_DIR='${APP_DIR}'
PYTHON_BIN='${VENV_DIR}/bin/python'
CONFIG_DIR='${CONFIG_DIR}'
DATA_DIR='${DATA_DIR}'
LOG_DIR='${LOG_DIR}'
EOF
  chmod 0644 "${CONFIG_DIR}/install.env"
}

write_wrapper() {
  mkdir -p "$(dirname "$BIN_PATH")"
  cat > "$BIN_PATH" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail

source "${CONFIG_DIR}/install.env"
exec "\$PYTHON_BIN" "\$APP_DIR/ngawolf_cli.py" --config "\$CONFIG_DIR/config.json" --data-dir "\$DATA_DIR" --log-file "\$LOG_DIR/watcher.log" "\$@"
EOF
  chmod 0755 "$BIN_PATH"
}

write_systemd_service() {
  if [[ "$INSTALL_SYSTEMD" == "0" ]]; then
    return
  fi

  if [[ ! -d /etc/systemd/system ]]; then
    log "systemd not detected; skipping service install."
    return
  fi

  local service_path="/etc/systemd/system/${SERVICE_NAME}.service"
  cat > "$service_path" <<EOF
[Unit]
Description=NGA Wolf Watcher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${BIN_PATH} run
Restart=on-failure
RestartSec=10
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
StandardOutput=append:${LOG_DIR}/watcher.log
StandardError=append:${LOG_DIR}/watcher.log

[Install]
WantedBy=multi-user.target
EOF

  chmod 0644 "$service_path"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
  fi
}

print_next_steps() {
  cat <<EOF

NGA Wolf installed.

Command:
  sudo ngawolf init
  sudo ngawolf check
  sudo ngawolf mark-seen
  sudo ngawolf test-send
  sudo ngawolf run
  sudo ngawolf start
  sudo ngawolf stop
  sudo ngawolf status
  sudo ngawolf logs -f
  sudo ngawolf config

Paths:
  config: ${CONFIG_DIR}/config.json
  data:   ${DATA_DIR}
  logs:   ${LOG_DIR}/watcher.log

If systemd is available:
  systemctl enable --now ${SERVICE_NAME}
  systemctl status ${SERVICE_NAME}

EOF
}

main() {
  require_root
  install_os_dependencies
  need_command curl
  need_command tar
  install_application_files
  install_python_environment
  write_install_env
  write_wrapper
  write_systemd_service
  print_next_steps
}

main "$@"
