# Safe FTP Deploy

A drop-in replacement for the manual "rename old file → upload new file" flow
you're currently doing in FileZilla, built so it's safe to hand to an AI
agent without fear of it wiping your server.

## Install

```bash
pip install cryptography --break-system-packages   # if not already installed
```

## 1. One-time setup per site

```bash
python3 safe_ftp_deploy.py setup-site --name mysite
```

You'll be prompted for:
- A **master password** (encrypts the credentials file — this password is never
  saved anywhere; you type it every time you use the tool)
- FTP host, port, username, password
- A whitelist of remote directories this site is allowed to touch
  (e.g. `/public_html/,/public_html/blog/`) — anything outside this is refused,
  even if an agent tells the tool to go there.

Credentials are stored encrypted (AES via Fernet, key derived from your master
password with PBKDF2-SHA256, 480k iterations) in `~/.safe_ftp_deploy/sites.enc`.
The password itself never touches disk.

## 2. Everyday use

**Always dry-run first (this is the default — nothing happens unless you pass `--execute`):**

```bash
python3 safe_ftp_deploy.py deploy --name mysite --local ./index.php --remote /public_html/index.php
```

**When the dry-run looks right, actually deploy:**

```bash
python3 safe_ftp_deploy.py deploy --name mysite --local ./index.php --remote /public_html/index.php --execute
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
python3 safe_ftp_deploy.py batch-deploy --name mysite --local-dir ./site --remote-dir /public_html --execute
```

**Check for drift without touching anything:**

```bash
python3 safe_ftp_deploy.py status --name mysite --remote /public_html/index.php
```

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
python3 safe_ftp_deploy.py download --name mysite --remote /public_html/config.php --local ./config.php

# Actually download
python3 safe_ftp_deploy.py download --name mysite --remote /public_html/config.php --local ./config.php --execute
```

**Bulk download an entire remote folder:**

```bash
python3 safe_ftp_deploy.py batch-download --name mysite --remote-dir /public_html --local-dir ./site_backup --execute
```

## Filtering bulk operations (include/exclude)

Both `batch-deploy` and `batch-download` accept comma-separated glob patterns,
so you don't accidentally bulk-touch vendor folders, logs, or caches:

```bash
python3 safe_ftp_deploy.py batch-deploy --name mysite \
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

Don't give an agent raw FTP access or an unrestricted FTP MCP server. Instead:

1. Let the agent decide *what* changed and *what* should be deployed.
2. Have the agent invoke this script as a subprocess with `--json`, e.g.:
   ```bash
   python3 safe_ftp_deploy.py deploy --name mysite --local ./index.php --remote /public_html/index.php --json
   ```
   (leave off `--execute` so the agent gets a dry-run plan first)
3. Show the JSON result to yourself (or have the agent summarize it) before
   ever adding `--execute`.
4. This script — not the agent — enforces the whitelist, drift protection,
   and no-delete guarantee, so even if the agent is confidently wrong about
   something, the underlying safety checks still apply.

If you want, this can also be wrapped as a single custom MCP tool later, but
running it as a subprocess the agent calls is the simplest and safest starting
point — you don't need to build or trust a new MCP server just to get this
benefit.

## Known limitation to keep in mind

The master password is prompted interactively each run (`getpass`) by
default, so fully unattended/scheduled automation isn't set up here by
default — that was intentional, since you mentioned wanting to avoid
unattended mishaps.

### Optional: skip the prompt with `.masterpwd`

If you'd rather not type the master password every run, create a file named
`.masterpwd` next to `safe_ftp.py` containing just the password, one line,
nothing else. When present, every command reads it from there instead of
prompting.

```
safe_ftp/.masterpwd
```

**This trades away the tool's "password never touches disk" guarantee** —
the file is plain text. Only use it if you've accepted that tradeoff:
- Never back it up anywhere, never copy it off this machine, never let it
  anywhere near the site being deployed to.
- Delete the file (or empty it) to go back to interactive prompting at any
  time — an empty file falls back to `getpass` automatically.
- It's a local convenience file, not a secret store — the actual FTP
  credentials stay encrypted in `sites.enc` either way; this file only
  unlocks that encryption.
