#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${NGAWOLF_REPO:-huangbwww/nga-wolf-watcher}"
VERSION="${NGAWOLF_VERSION:-latest}"
SOURCE_DIR="${NGAWOLF_SOURCE_DIR:-}"
ARCHIVE_URL="${NGAWOLF_ARCHIVE_URL:-}"
GITHUB_PROXY="${NGAWOLF_GITHUB_PROXY:-}"
PACKAGE_URL="${NGAWOLF_PACKAGE_URL:-}"
CHECKSUMS_URL="${NGAWOLF_CHECKSUMS_URL:-}"
INSTALL_FROM_SOURCE="${NGAWOLF_INSTALL_FROM_SOURCE:-0}"
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
INSTALL_KIND="source"

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
  local include_python="${1:-1}"

  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    local packages=(curl ca-certificates tar)
    if [[ "$include_python" == "1" ]]; then
      packages+=(python3 python3-venv python3-pip)
    fi
    apt-get install -y "${packages[@]}"
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    local packages=(curl ca-certificates tar)
    if [[ "$include_python" == "1" ]]; then
      packages+=(python3 python3-pip)
    fi
    dnf install -y "${packages[@]}"
    return
  fi

  if command -v yum >/dev/null 2>&1; then
    local packages=(curl ca-certificates tar)
    if [[ "$include_python" == "1" ]]; then
      packages+=(python3 python3-pip)
    fi
    yum install -y "${packages[@]}"
    return
  fi

  if command -v zypper >/dev/null 2>&1; then
    local packages=(curl ca-certificates tar)
    if [[ "$include_python" == "1" ]]; then
      packages+=(python3 python3-pip)
    fi
    zypper --non-interactive install "${packages[@]}"
    return
  fi

  if command -v pacman >/dev/null 2>&1; then
    local packages=(curl ca-certificates tar)
    if [[ "$include_python" == "1" ]]; then
      packages+=(python python-pip)
    fi
    pacman -Sy --noconfirm --needed "${packages[@]}"
    return
  fi

  log "No supported package manager detected; assuming Python, curl, and tar are already installed."
}

github_url() {
  local url="$1"
  if [[ -n "$GITHUB_PROXY" ]]; then
    printf '%s\n' "${GITHUB_PROXY%/}/$url"
  else
    printf '%s\n' "$url"
  fi
}

resolve_latest_version() {
  local latest_url
  latest_url="$(curl -fsSIL -o /dev/null -w '%{url_effective}' "$(github_url "https://github.com/${REPO}/releases/latest")")"
  [[ "$latest_url" != */tag/* ]] && die "Could not resolve latest release for ${REPO}"
  local resolved="${latest_url##*/tag/}"
  resolved="${resolved%%[?#]*}"
  resolved="${resolved%%/}"
  printf '%s\n' "$resolved"
}

download_release_source() {
  local resolved_version="$1"
  local archive_path="$2"
  local archive_url
  if [[ -n "$ARCHIVE_URL" ]]; then
    archive_url="$ARCHIVE_URL"
  else
    archive_url="$(github_url "https://github.com/${REPO}/archive/refs/tags/${resolved_version}.tar.gz")"
  fi

  log "Downloading ${REPO} ${resolved_version}"
  curl -fL "$archive_url" -o "$archive_path"
}

detect_package_arch() {
  local machine
  machine="$(uname -m)"
  case "$machine" in
    x86_64|amd64)
      printf '%s\n' "x86_64"
      ;;
    aarch64|arm64)
      printf '%s\n' "aarch64"
      ;;
    *)
      return 1
      ;;
  esac
}

download_release_package() {
  local resolved_version="$1"
  local package_path="$2"
  local package_arch="$3"
  local package_url

  if [[ -n "$PACKAGE_URL" ]]; then
    package_url="$PACKAGE_URL"
  else
    local asset_name="nga-wolf-watcher-${resolved_version}-linux-${package_arch}.tar.gz"
    package_url="$(github_url "https://github.com/${REPO}/releases/download/${resolved_version}/${asset_name}")"
  fi

  log "Downloading Linux package ${resolved_version} ${package_arch}"
  curl -fL "$package_url" -o "$package_path"
}

download_release_checksums() {
  local resolved_version="$1"
  local checksums_path="$2"
  local checksums_url

  if [[ -n "$CHECKSUMS_URL" ]]; then
    checksums_url="$CHECKSUMS_URL"
  else
    checksums_url="$(github_url "https://github.com/${REPO}/releases/download/${resolved_version}/SHA256SUMS")"
  fi

  curl -fL "$checksums_url" -o "$checksums_path"
}

verify_package_checksum() {
  local package_path="$1"
  local asset_name="$2"
  local resolved_version="$3"

  if [[ -n "$PACKAGE_URL" && -z "$CHECKSUMS_URL" ]]; then
    log "Skipping checksum verification for custom NGAWOLF_PACKAGE_URL without NGAWOLF_CHECKSUMS_URL."
    return
  fi

  local checksums_path="${TMP_DIR}/SHA256SUMS"
  local check_line="${TMP_DIR}/SHA256SUMS.one"
  download_release_checksums "$resolved_version" "$checksums_path"
  awk -v name="$asset_name" '$2 == name { print; found=1 } END { exit found ? 0 : 1 }' "$checksums_path" > "$check_line" || die "SHA256SUMS does not contain ${asset_name}"
  (
    cd "$(dirname "$package_path")"
    sha256sum -c "$check_line"
  )
}

install_binary_package() {
  local package_path="$1"
  local target="$2"

  tar -xzf "$package_path" -C "$target" --strip-components=1
  [[ -x "${target}/ngawolf" ]] || return 1
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
  INSTALL_KIND="source"

  if [[ -n "$SOURCE_DIR" ]]; then
    log "Installing from local source: ${SOURCE_DIR}"
    copy_source_dir "$SOURCE_DIR" "$next_app"
  else
    local resolved_version="$VERSION"
    if [[ "$resolved_version" == "latest" && -z "$ARCHIVE_URL" && -z "$PACKAGE_URL" ]]; then
      resolved_version="$(resolve_latest_version)"
    fi
    local package_arch=""
    package_arch="$(detect_package_arch || true)"

    if [[ "$INSTALL_FROM_SOURCE" != "1" && ( -n "$PACKAGE_URL" || -n "$package_arch" ) ]]; then
      local asset_name="nga-wolf-watcher-${resolved_version}-linux-${package_arch}.tar.gz"
      if [[ -n "$PACKAGE_URL" ]]; then
        asset_name="$(basename "${PACKAGE_URL%%[?#]*}")"
      fi
      local package_path="${TMP_DIR}/${asset_name}"
      if download_release_package "$resolved_version" "$package_path" "${package_arch:-custom}"; then
        verify_package_checksum "$package_path" "$asset_name" "$resolved_version"
        if install_binary_package "$package_path" "$next_app"; then
          INSTALL_KIND="binary"
        else
          log "Downloaded Linux package is not usable; falling back to source install."
          rm -rf "$next_app"
          mkdir -p "$next_app"
        fi
      else
        log "Linux package is unavailable; falling back to source install."
      fi
    fi

    if [[ "$INSTALL_KIND" == "source" ]]; then
      if [[ "$resolved_version" == "latest" && -z "$ARCHIVE_URL" ]]; then
        resolved_version="$(resolve_latest_version)"
      fi
      local archive_path="${TMP_DIR}/ngawolf-source.tar.gz"
      download_release_source "$resolved_version" "$archive_path"
      tar -xzf "$archive_path" -C "$next_app" --strip-components=1
    fi
  fi

  if [[ "$INSTALL_KIND" == "binary" ]]; then
    [[ -x "${next_app}/ngawolf" ]] || die "Downloaded Linux package does not contain executable ngawolf"
  else
    [[ -f "${next_app}/ngawolf_cli.py" ]] || die "Downloaded archive does not contain ngawolf_cli.py"
  fi
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
  local app_exec=""
  if [[ "$INSTALL_KIND" == "binary" ]]; then
    app_exec="${APP_DIR}/ngawolf"
  fi
  cat > "${CONFIG_DIR}/install.env" <<EOF
APP_DIR='${APP_DIR}'
PYTHON_BIN='${VENV_DIR}/bin/python'
APP_EXEC='${app_exec}'
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
if [[ -n "\${APP_EXEC:-}" && -x "\$APP_EXEC" ]]; then
  exec "\$APP_EXEC" --config "\$CONFIG_DIR/config.json" --data-dir "\$DATA_DIR" --log-file "\$LOG_DIR/watcher.log" "\$@"
fi
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
  install_os_dependencies 0
  need_command curl
  need_command tar
  install_application_files
  if [[ "$INSTALL_KIND" == "source" ]]; then
    install_os_dependencies 1
    install_python_environment
  fi
  write_install_env
  write_wrapper
  write_systemd_service
  print_next_steps
}

main "$@"
