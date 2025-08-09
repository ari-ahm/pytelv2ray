## Universal Proxy Scanner

This tool scans configured Telegram groups for proxy links, tests them with `xray-knife`, stores results in SQLite, and can optionally upload the best servers to a GitHub repository as a subscription file.

## Features

- **Proxy harvesting from Telegram**: Extracts `vless`, `vmess`, `ss`, `ssr`, and `trojan` URIs.
- **Asynchronous pipeline**: Non-blocking I/O with `asyncio` and `aiosqlite`.
- **Latency and selective speed tests**: Uses `xray-knife` for both latency checks and optional speed tests.
- **Persistence and curation**: Keeps historical results, caps servers per location, and retries failed links.
- **Optional GitHub upload**: Updates or creates a repo file with the final subscription content. Set `github_repo.upload_base64` to true if you need to store base64 content; otherwise raw text is uploaded.
- **Graceful shutdown**: Safely interrupts long-running tasks on SIGINT/SIGTERM.

## Requirements

- Python 3.10+
- Packages (installed via `requirements.txt`):
  - `telethon`
  - `aiosqlite`
  - `PyGithub`
  - `pytest`, `pytest-asyncio` (for tests)
  - If using a SOCKS proxy for Telegram, ensure `PySocks` is installed
- External binary: `xray-knife` (see below)

## Install

```bash
pip install -r requirements.txt
```

## External binary: xray-knife

- Download from the releases page: `https://github.com/lilendian0x00/xray-knife/releases`
- Extract the executable and make sure it is executable (`chmod +x xray-knife` on Linux/macOS).
- Set `xray_knife.path` in `config.json` to the executable path. Example: `"./xray-knife/xray-knife"`.

## Configuration

Edit `config.json` with your values. Example:

```json
{
  "telegram": {
    "api_id": 1234567,
    "api_hash": "YOUR_API_HASH",
    "session_name": "my_telegram_session",
    "target_groups": [-1001234567890],
    "fetch_chunk_size": 200,
    "proxy": {
      "enabled": false,
      "scheme": "socks5",
      "hostname": "127.0.0.1",
      "port": 9050
    }
  },
  "xray_knife": {
    "path": "./xray-knife/xray-knife",
    "test_args": ["-t", "20"]
  },
  "internal_proxy": {
    "enabled": false,
    "selector": "speed_passed",
    "max_links": 1,
    "listen_host": "127.0.0.1",
    "listen_port": 1080,
    "xray_knife_args": []
  },
  "speed_test": {
    "enabled": true,
    "min_download_mbps": 5.0,
    "max_candidates_per_location": 3
  },
  "github_repo": {
    "enabled": true,
    "github_token": "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN",
    "owner": "YOUR_GITHUB_USERNAME",
    "repo": "YOUR_REPO_NAME",
    "file_path": "path/to/subscription.txt",
    "commit_message": "Update proxy subscription"
  },
  "logging": {
    "level": "INFO",
    "file": "scanner.log"
  },
  "database": {
    "path": "servers.db",
    "retest_window_hours": 6,
    "max_retries": 3,
    "max_servers_per_location": 10
  }
}
```

Notes:
- `telegram.api_hash` must be set (the app validates this and will exit if it is a placeholder).
- `xray_knife.path` must point to the actual executable (the app validates it with your system PATH). If the file is inside a folder like `xray-knife/xray-knife`, set that exact path.
- `speed_test.min_download_mbps` is currently a reserved field for future filtering; the best server per location is chosen by highest measured download speed.

## How it works

1. Collect recent messages from all configured Telegram groups and extract proxy links.
2. Run `xray-knife` latency tests on new links plus eligible retries; persist results in SQLite.
3. Optionally select top latency-passed candidates per location and run speed tests; persist results and pick the best per location.
4. If enabled, upload a base64-encoded subscription (newline-separated links) to the configured GitHub repo/file.

### Optional: Run through your own internal proxy

When `internal_proxy.enabled` is true, the app will:
- Pick one or more of the best links from the database (by `selector`) and start an `xray-knife` local SOCKS5 proxy.
- Route Telegram collection through this local proxy.

Config options:
- `selector`: `speed_passed` (download desc) or `latency_passed` (delay asc)
- `max_links`: number of links to feed to the internal proxy
- `listen_host` / `listen_port`: where the local SOCKS5 listens
- `xray_knife_args`: extra CLI flags passed to `xray-knife proxy` (advanced)

## Run

```bash
python app.py
```

On first run, Telethon will prompt for your phone number, login code, and 2FA (if enabled) to create the `.session` file.

Logs are written to `scanner.log` by default; optional rotation can be enabled via `logging.rotate`.

## Scheduling (optional)

Use cron/systemd to run periodically. Example crontab entry (every 30 minutes):

```cron
*/30 * * * * cd /path/to/project && /path/to/python app.py >> scanner.log 2>&1
```

## Troubleshooting

- Config error: Ensure `config.json` is valid JSON and required fields are not placeholders.
- `xray-knife binary not found`: Verify `xray_knife.path` points to an executable and is accessible (use an absolute path if needed).
- GitHub upload failures: Check token permissions (repo scope), repository name/owner, and that the file path is correct.

