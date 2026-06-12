# NGA Wolf Watcher Linux CLI

This archive contains the headless `ngawolf` CLI.

The release binary is built on Ubuntu 22.04 for glibc-based Linux distributions. If your system is very old or uses musl, use `install-linux.sh`; it can fall back to a source install.

Recommended installation is through `install-linux.sh`, which creates the wrapper command, config directory, state directory, log directory, and optional systemd service:

```bash
curl -fsSL https://github.com/huangbwww/nga-wolf-watcher/releases/latest/download/install-linux.sh | sudo bash
```

Direct use after extracting the archive:

```bash
./ngawolf init
./ngawolf config
./ngawolf check
./ngawolf run
```

Default installed paths:

- Config: `/etc/ngawolf/config.json`
- State: `/var/lib/ngawolf`
- Log: `/var/log/ngawolf/watcher.log`
- Command: `/usr/local/bin/ngawolf`
