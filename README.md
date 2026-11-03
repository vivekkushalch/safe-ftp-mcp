<div align="center">

<img src="assets/logo.svg" alt="Safe FTP MCP" width="420">

**FTP deploys you can hand to an AI agent without losing sleep.**<br>
Drift detection · no-delete guarantee · dry-run by default · MCP server included

[![CI](https://github.com/vivekkushalch/safe_ftp/actions/workflows/ci.yml/badge.svg)](https://github.com/vivekkushalch/safe_ftp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/badge/uv-compatible-green.svg)](https://docs.astral.sh/uv/)
[![MCP](https://img.shields.io/badge/MCP-server-8A2BE2.svg)](https://modelcontextprotocol.io)
[![Platforms](https://img.shields.io/badge/platform-windows%20%7C%20macos%20%7C%20linux-lightgrey.svg)](#installation)

[Quick start](#quick-start) · [Features](#features) · [Usage](#usage) · [AI agents](#ai-agent-integration) · [Safety model](#safety-model) · [FAQ](#faq) · [Contributing](#contributing)

</div>

---

## What is it?

Safe FTP Deploy is a drop-in replacement for the manual "rename old file, upload new file" routine you do in FileZilla. It never deletes anything, never overwrites blindly, and does nothing at all until you pass `--execute`.

That makes it safe to expose to an AI coding agent. The tool decides *how* a deploy happens, whatever the agent asks for.

```text
$ safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php

Deploy: ./index.php → /public_html/index.php

📝 Dry run — [DRY RUN] Would rename remote '/public_html/index.php' -> '/public_html/index_<timestamp>.php',
then upload local './index.php' as '/public_html/index.php'. Re-run with --execute to apply.
- Backup: /public_html/index_<timestamp>.php
```

## Why not just use FileZilla or raw FTP?

| | Plain FTP client / raw FTP MCP | Safe FTP Deploy |
|---|---|---|
| Can delete remote files | Yes | **No**, there is no delete code path |
| Overwrites a file someone edited on the server | Silently | **Refuses** (drift detection) |
| Default behavior | Writes immediately | **Dry-run** until `--execute` |
| Confirms the upload is intact | Rarely | Re-downloads and compares hashes |
| Scope of what an agent can touch | Whole account | Only whitelisted directories |
| Credentials | Often plain text | Encrypted at rest |

## Features

| | |
|---|---|
| 🛡️ **No delete capability** | The only destructive-looking operation is `rename`, which keeps the original bytes under a new name. |
| 🔍 **Drift detection** | Refuses to overwrite if the server file changed since your last deploy. Override with `--force`. |
| 🎯 **Dry-run by default** | Nothing is touched unless you pass `--execute`. |
| ✅ **Post-upload verification** | Re-downloads the file and compares hashes. |
| 📁 **Directory whitelist** | Limit which remote folders can ever be touched. |
| 🔐 **Encrypted credentials** | Fernet (AES) with a PBKDF2-SHA256 key, 480k iterations. |
| 🔒 **Verified TLS** | FTPS certificates and hostnames are checked by default. |
| 🕒 **Timestamped backups** | `DDMMYY_HHMMSS_microseconds`, so names never collide. |
| 📜 **Deploy history** | Attach notes with `-m` and review them later. |
| 🤖 **MCP server** | Eight tools, one-command install for Claude Code, Cursor, Windsurf, OpenCode and Antigravity. |
| 🧠 **Agent skill** | Bundled `safe-ftp-deploy` skill teaches agents the dry-run-first workflow. Installed automatically by `install`. |

## Quick start

**1. Install** (needs [`uv`](https://docs.astral.sh/uv/getting-started/installation/)):

```bash
uv tool install git+https://github.com/vivekkushalch/safe_ftp.git
```

**2. Set up a site** (once per project folder):

```bash
safe-ftp-deploy setup-site --name mysite
```

You'll be asked for a master password (encrypts the credentials, never saved to disk), the FTP host, port, username and password, and the allowed remote directories, e.g. `/public_html/,/public_html/blog/`.

**3. Deploy:**

```bash
# Dry-run first
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php

# Looks right? Do it.
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php --execute
```

What happens on `--execute`:

1. Download and hash the current remote file.
2. Compare against the last known hash (drift check).
3. Rename the old file to a timestamped backup.
4. Upload the new file.
5. Re-download and verify it matches.

## Installation

Works the same on Windows, macOS and Linux.

```bash
# install
uv tool install git+https://github.com/vivekkushalch/safe_ftp.git

# update
uv tool upgrade safe-ftp-deploy
```

<details>
<summary>Install from source (for development)</summary>

```bash
git clone https://github.com/vivekkushalch/safe_ftp.git
cd safe_ftp
uv sync
uv run safe-ftp-deploy --help
```

</details>

## Setup

### Interactive

```bash
safe-ftp-deploy setup-site --name mysite
```

Credentials are stored encrypted in `~/.safe_ftp_deploy/sites.enc`.

### Non-interactive

```bash
safe-ftp-deploy setup-site --name mysite --non-interactive \
  --host ftp.example.com --port 21 --username myuser \
  --use-tls --allowed-dirs "/public_html/,/public_html/blog/"
```

### TLS and certificates

FTPS connections verify the server certificate and hostname by default. If your host uses a self-signed or mismatched certificate and you trust it, opt out when saving the site:

```bash
safe-ftp-deploy setup-site --name mysite --insecure-tls
```

> [!WARNING]
> `--insecure-tls` leaves the connection open to interception. Use it only on hosts you trust. It is not exposed through the MCP `setup_site` tool, so an agent can't turn verification off.

Pass passwords through environment variables so they stay out of shell history:

| Variable | Purpose |
|---|---|
| `SAFE_FTP_FTP_PASSWORD` | FTP password |
| `SAFE_FTP_MASTER_PASSWORD` | Master password |

`--ftp-password` and `--master-password` flags also work but are less safe.

### Import from FileZilla

```bash
safe-ftp-deploy setup-site --name mysite --from-filezilla ./export.xml
```

Use a Site Manager XML export containing exactly one `<Server>`. It pre-fills host, port, username, password and TLS. You'll still be asked for the directory whitelist unless you pass `--allowed-dirs`.

> [!NOTE]
> FileZilla exports protected by a master password (`encoding="crypt"`) can't be decrypted. Re-export without one, or pass `--ftp-password` yourself.

## Usage

`--name` is optional once `setup-site` has run in a folder: it defaults to the site in `.ftpconfig`.

### Commands

| Command | What it does |
|---|---|
| `setup-site` | Add or update an encrypted site profile |
| `deploy` | Deploy one file |
| `batch-deploy` | Deploy a whole local folder |
| `download` | Download one remote file |
| `batch-download` | Download a whole remote folder |
| `status` | Check a remote file for drift, change nothing |
| `history` | Show past deploys (read-only) |
| `list` | List a remote directory (read-only) |
| `mcp` | Start the MCP server |
| `install` | Wire the MCP server and skill into an AI agent |

Every write command is a dry-run until you add `--execute`.

### Deploy

```bash
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php --execute
safe-ftp-deploy batch-deploy --local-dir ./site --remote-dir /public_html --execute
```

### Download

Local files are renamed to timestamped backups before being overwritten.

```bash
safe-ftp-deploy download --remote /public_html/config.php --local ./config.php --execute
safe-ftp-deploy batch-download --remote-dir /public_html --local-dir ./site_backup --execute
```

### Filter bulk operations

Keep vendor folders, logs and caches out of the blast radius:

```bash
safe-ftp-deploy batch-deploy \
  --local-dir ./site --remote-dir /public_html \
  --include "*.php,*.css,*.js" \
  --exclude "vendor/*,*.log,cache/*" \
  --execute
```

### History

```bash
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php \
  --execute -m "fix checkout redirect loop"

safe-ftp-deploy history --remote /public_html/index.php
```

History is stored locally (timestamp, message, hash, backup filename). Shows 10 entries by default; change with `--limit`.

### Check for drift

```bash
safe-ftp-deploy status --remote /public_html/index.php
```

## AI agent integration

**Don't give an agent raw FTP access.** Give it this instead.

### MCP server (recommended)

```bash
safe-ftp-deploy mcp
```

Exposes eight tools: `deploy`, `batch_deploy`, `download`, `batch_download`, `status`, `history`, `list_remote`, `setup_site`. Every write tool defaults to `execute=False`, so the agent has to opt in to change anything.

**One-command install:**

```bash
safe-ftp-deploy install claude       # Claude Code
safe-ftp-deploy install cursor       # Cursor
safe-ftp-deploy install windsurf     # Windsurf (global)
safe-ftp-deploy install opencode     # OpenCode
safe-ftp-deploy install antigravity  # Antigravity
safe-ftp-deploy install all          # everything above
```

This merges an MCP entry into the agent's config (existing entries are kept) and installs the bundled [`safe-ftp-deploy` skill](skill/safe-ftp-deploy/SKILL.md), which tells the agent to dry-run first, relay the summary to you, and never work around the guardrails.

**Manual config:**

```json
{"mcpServers": {"safe-ftp-deploy": {"command": "safe-ftp-deploy", "args": ["mcp"]}}}
```

### CLI with JSON output

No MCP? Have the agent call the CLI with `--json` for structured output, and leave off `--execute` so it gets a dry-run plan first.

```bash
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php --json
```

## Safety model

| Guarantee | How |
|---|---|
| No file is ever deleted | The tool has no delete code path. Replaced files are renamed, not removed. |
| No silent overwrite | Remote hash is checked against the last deploy. Mismatch aborts unless `--force`. |
| No surprise writes | Dry-run is the default everywhere, including in MCP tools. |
| No bad uploads | Every upload is re-downloaded and hashed. |
| No wandering | Writes outside the directory whitelist are rejected. |
| No plaintext credentials | Encrypted at rest, decrypted only in memory. |
| No unverified TLS | Certificates and hostnames are verified unless you pass `--insecure-tls` at setup. |

## Configuration

### `.ftpconfig` (optional)

`setup-site` writes a `.ftpconfig` in the current directory:

- Line 1: default site name
- Line 2: master password

With it present you skip the password prompt and the `--name` flag in that folder. Delete it to go back to prompting.

> [!WARNING]
> This trades away the "password never touches disk" guarantee. The file is plain text. Don't back it up, copy it off the machine, or deploy it to the server. Add `.ftpconfig` to your `.gitignore`.

### Migrating from `.masterpwd`

The next `setup-site` run moves an old `.masterpwd` into `.ftpconfig` automatically. You can delete `.masterpwd` afterwards.

## FAQ

**Can it delete files?**
No. There is no delete code path. Replaced files are renamed to timestamped backups, so you clean up old backups yourself.

**What if the server file changed since my last deploy?**
You get `drift_detected` and nothing is written. Review the server version, then re-run with `--force` if you're sure.

**Does it work with SFTP?**
No, FTP and FTPS only.

**Where are my credentials stored?**
Encrypted in `~/.safe_ftp_deploy/sites.enc`. The master password is never saved unless you keep the optional `.ftpconfig`.

**Can an AI agent bypass the guardrails?**
Not through the tool: dry-run, drift checks and the directory whitelist are enforced inside it, and `--insecure-tls` isn't exposed over MCP. An agent with shell access to your machine can still read your files, so treat `.ftpconfig` accordingly.

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability privately.

## Development

```bash
uv sync
uv run pytest
```

| File | Role |
|---|---|
| `safe_ftp.py` | CLI and core deploy logic |
| `safe_ftp_mcp.py` | MCP server |
| `safe_ftp_install.py` | `install` command for agent configs |
| `safe_ftp_format.py` | Output formatting |
| `skill/` | Agent skill installed by `install` |
| `tests/` | Test suite |

## Contributing

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first.

Changes must keep the core promise: no delete path, no write without `--execute`. See the [CHANGELOG](CHANGELOG.md) for release notes.

## License

[MIT](LICENSE)
