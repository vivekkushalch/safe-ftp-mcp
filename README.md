# Safe FTP Deploy

A drop-in replacement for the manual "rename old file → upload new file" flow
you're currently doing in FileZilla, built so it's safe to hand to an AI
agent without fear of it wiping your server.

## Contents

- [Install](#install)
- [One-time setup per site](#1-one-time-setup-per-site)
  - [Non-interactive / scripted setup](#non-interactive--scripted-setup)
  - [Importing from FileZilla](#importing-from-filezilla)
- [Everyday use](#2-everyday-use)
- [Custom / dynamic paths](#custom--dynamic-paths)
- [Download (single file and bulk)](#download-single-file-and-bulk)
- [Filtering bulk operations](#filtering-bulk-operations-includeexclude)
- [Safety guarantees](#safety-guarantees)
- [Using this safely with an AI coding agent](#using-this-safely-with-an-ai-coding-agent)
- [Known limitation to keep in mind](#known-limitation-to-keep-in-mind)

## Install

Requires [`uv`](https://docs.astral.sh/uv/getting-started/installation/):

```bash
uv tool install git+https://github.com/vivekkushalch/safe_ftp.git
```

This installs a `safe-ftp-deploy` command on your PATH. Works the same way
on Windows, macOS, and Linux — no separate Python/pip setup beyond having
`uv` installed.

### Updating

```bash
uv tool upgrade safe-ftp-deploy
```

That's the entire update process — `uv` re-pulls and rebuilds from the repo.
There's no separate update command or background version check built into
the tool itself.

## 1. One-time setup per site

```bash
safe-ftp-deploy setup-site --name mysite
```

Run this once per project directory (its working directory is what makes
the config that follows project-specific). You'll be prompted for:
- A **master password** (encrypts the credentials file — this password is never
  saved anywhere; you type it every time you use the tool)
- FTP host, port, username, password
- A whitelist of remote directories this site is allowed to touch
  (e.g. `/public_html/,/public_html/blog/`) — anything outside this is refused,
  even if an agent tells the tool to go there.

Credentials are stored encrypted (AES via Fernet, key derived from your master
password with PBKDF2-SHA256, 480k iterations) in `~/.safe_ftp_deploy/sites.enc`.
The password itself never touches disk.

### Non-interactive / scripted setup

Every field can be supplied without prompts, for automation or bulk setup:

```bash
safe-ftp-deploy setup-site --name mysite --non-interactive \
  --host ftp.example.com --port 21 --username myuser \
  --ftp-password "$FTP_PW" --master-password "$MASTER_PW" \
  --use-tls --allowed-dirs "/public_html/,/public_html/blog/"
```

`--non-interactive` requires every field to resolve from a flag, an
environment variable, or `--from-filezilla` (below) — it errors out
listing exactly what's missing rather than silently prompting or guessing.

- `--ftp-password` can also come from `SAFE_FTP_FTP_PASSWORD`.
- `--master-password` can also come from `SAFE_FTP_MASTER_PASSWORD`, or
  from an existing `.ftpconfig`/`.masterpwd` already in this directory.
- `--use-tls`/`--no-tls` and `--allowed-dirs` have safe defaults (TLS on,
  empty whitelist) if omitted, so they're never required.
- Environment variables are preferred over flags for passwords when you
  have the choice — flags land in shell history and process listings,
  env vars don't.

### Importing from FileZilla

If you already have the site saved in FileZilla, point `setup-site` at a
Site Manager XML export instead of typing the connection details:

```bash
safe-ftp-deploy setup-site --name mysite --from-filezilla ./export.xml
```

The export must contain exactly one `<Server>` entry — trim a multi-site
export down first. This pre-fills host, port, username, password, and TLS;
you're still prompted for the allowed-dirs whitelist unless you also pass
`--allowed-dirs` (or `--non-interactive`, in which case it defaults to
empty with the usual warning). Any explicit flag (`--host`, `--use-tls`,
etc.) overrides the imported value for that field.

Passwords protected by a FileZilla *master* password (`encoding="crypt"`
in the export) can't be decrypted by this tool — re-export without one, or
pass `--ftp-password`/`SAFE_FTP_FTP_PASSWORD` yourself.

## 2. Everyday use

`--name` is optional after `setup-site` has run once in this folder — it
defaults to the site recorded in `.ftpconfig` for the current directory.
Pass `--name <site>` explicitly any time you want to target a different
site ad hoc.

**Always dry-run first (this is the default — nothing happens unless you pass `--execute`):**

```bash
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php
```

**When the dry-run looks right, actually deploy:**

```bash
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php --execute
```

This will:
1. Download the current remote file and hash it.
2. Compare it against the hash from the *last time this tool deployed it*.
   - If someone changed the server file outside this tool (direct edit, another
     deploy, etc.), it stops and tells you — it will not overwrite silently.
3. Rename the remote file to `index_270726_143210_482391.php` — format is
   `DDMMYY_HHMMSS_microseconds`, so even multiple files backed up within the
   same second during a batch run never collide on filename.
4. Upload the new file.
5. Re-download and hash it again to confirm the upload actually matches your local file.

**Deploy a whole folder the same way:**

```bash
safe-ftp-deploy batch-deploy --local-dir ./site --remote-dir /public_html --execute
```

**Check for drift without touching anything:**

```bash
safe-ftp-deploy status --remote /public_html/index.php
```

**Attach a note to a deploy, and look back at it later:**

```bash
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php --execute -m "fix checkout redirect loop"

safe-ftp-deploy history --remote /public_html/index.php
```

`--message`/`-m` is optional on both `deploy` and `batch-deploy` (one message
covers every file in a batch run). It's only recorded when a deploy actually
executes successfully — dry-runs and failed deploys don't get a history
entry. `history` is read-only and never contacts the server: it just reads
the local log of past deploys for that remote path (timestamp, message,
resulting hash, and which backup file it replaced), most recent first,
capped at 10 entries by default (`--limit` to change that).

## Custom / dynamic paths

`--local` and `--remote` (and `--local-dir` / `--remote-dir`) are plain arguments —
point them at whatever path you need at the time. Nothing is hardcoded, so this
works fine from a wrapper script or an agent that computes the path dynamically
each time.

## Download (single file and bulk)

Same safety model, mirrored for the download direction: if a local file already
exists and would be overwritten, it's renamed to a timestamped backup first —
never deleted — and the download is verified by hash afterward.

```bash
# Dry-run
safe-ftp-deploy download --remote /public_html/config.php --local ./config.php

# Actually download
safe-ftp-deploy download --remote /public_html/config.php --local ./config.php --execute
```

**Bulk download an entire remote folder:**

```bash
safe-ftp-deploy batch-download --remote-dir /public_html --local-dir ./site_backup --execute
```

## Filtering bulk operations (include/exclude)

Both `batch-deploy` and `batch-download` accept comma-separated glob patterns,
so you don't accidentally bulk-touch vendor folders, logs, or caches:

```bash
safe-ftp-deploy batch-deploy \
  --local-dir ./site --remote-dir /public_html \
  --include "*.php,*.css,*.js" \
  --exclude "vendor/*,*.log,cache/*" \
  --execute
```

## Safety guarantees

- **No delete capability exists in this tool at all.** The only "risky" FTP
  operation used is `rename`, and renaming preserves the original bytes under
  a new name — nothing is ever destroyed.
- **Drift detection.** If the file on the server doesn't match what this tool
  last put there, it refuses to proceed rather than guessing. You can override
  with `--force` only after you've manually confirmed it's safe.
- **Dry-run by default.** You have to explicitly pass `--execute` for anything
  to actually happen.
- **Post-upload verification.** After uploading, it re-downloads and hashes the
  file to confirm the upload matches — it doesn't just assume `STOR` succeeded.
- **Directory whitelist.** Each site profile can restrict which remote folders
  are touchable at all.
- **Encrypted credentials at rest**, decrypted only in memory for the duration
  of a run, using a password that is never written to disk.

## Using this safely with an AI coding agent

Don't give an agent raw FTP access or an unrestricted FTP MCP server.
Instead, this tool decides *how* a deploy happens — dry-run first, drift
protection, the directory whitelist — regardless of what the agent asks
for. There are two ways to hand it to an agent:

### Option 1: MCP server (recommended)

```bash
safe-ftp-deploy mcp
```

Starts an MCP server (stdio transport) exposing eight tools —
`deploy`, `batch_deploy`, `download`, `batch_download`, `status`,
`history`, `list_remote`, `setup_site` — mirroring the CLI subcommands 1:1. Every
write tool defaults to `execute=False`, identical to the CLI's
`--execute` requirement: the agent must explicitly opt in to actually
changing anything.

**One-command setup for a specific agent**, run from the project
directory you'll be deploying from:

```bash
safe-ftp-deploy install claude       # Claude Code
safe-ftp-deploy install cursor       # Cursor
safe-ftp-deploy install windsurf     # Windsurf (registers globally -- Windsurf has no project-level config)
safe-ftp-deploy install opencode     # OpenCode
safe-ftp-deploy install antigravity  # Antigravity
safe-ftp-deploy install all          # all of the above at once
```

This merges an MCP server entry into that agent's config file (existing
entries are always preserved — it only ever adds/updates the
`safe-ftp-deploy` entry, and refuses rather than overwrites if the file
isn't valid JSON) and installs the safe-dry-run-then-confirm workflow
guidance: a real skill for Claude Code
(`.claude/skills/safe-ftp-deploy/SKILL.md`), or an `AGENTS.md` section for
the others, since they don't have a native skill mechanism.

Prefer manual setup instead? Point your agent's MCP config at it directly:

```json
{"mcpServers": {"safe-ftp-deploy": {"command": "safe-ftp-deploy", "args": ["mcp"]}}}
```

The skill content that `install claude` writes also ships as a plain file
at [`skill/safe-ftp-deploy/SKILL.md`](skill/safe-ftp-deploy/SKILL.md) if
you'd rather copy it yourself.

### Option 2: CLI subprocess

If MCP isn't available, have the agent invoke the CLI directly with
`--json` so it gets structured output instead of scraping text:

```bash
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php --json
```

(leave off `--execute` so the agent gets a dry-run plan first, then show
the result to yourself before ever adding `--execute`)

If the agent also needs to provision a *new* site (not just deploy to an
existing one), `setup-site --non-interactive` avoids it having to fake
interactive prompts — see "Non-interactive / scripted setup" above. The
MCP `setup_site` tool works the same way, non-interactively by design.

## Known limitation to keep in mind

The master password is prompted interactively each run (`getpass`) by
default, so fully unattended/scheduled automation isn't set up here by
default — that was intentional, to avoid unattended mishaps. `.ftpconfig`
(below) and `setup-site --non-interactive` both opt back into unattended
use deliberately, on a per-directory or per-command basis — the default
stays interactive unless you explicitly set one of those up.

### Optional: skip the prompt with `.ftpconfig`

`setup-site` writes a `.ftpconfig` file in the directory you ran it from,
containing the default site name (line 1) and the master password (line 2)
for that project. Every other command reads it from the current directory,
so once it exists you don't need to type the master password or pass
`--name` again in that folder.

```
myproject/.ftpconfig
```

**This trades away the tool's "password never touches disk" guarantee** —
the file is plain text. Only use it if you've accepted that tradeoff:
- Never back it up anywhere, never copy it off this machine, never let it
  anywhere near the site being deployed to.
- Delete the file (or empty it) to go back to interactive prompting and
  explicit `--name` at any time.
- It's a local convenience file, not a secret store — the actual FTP
  credentials stay encrypted in `sites.enc` either way; this file only
  unlocks that encryption and picks the default site.

If you already have an old `.masterpwd` file from a previous version, the
next `setup-site` run migrates it into `.ftpconfig` automatically and prints
a note once that's done — you can delete `.masterpwd` after that.
