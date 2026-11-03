---
name: safe-ftp-deploy
description: Use when deploying, downloading, or checking files on FTP/FTPS shared hosting (e.g. Hostinger) via the safe-ftp-deploy tool. Trigger on requests to deploy/upload/publish a file or folder to an FTP site, download files from one, check drift/deploy status, list a remote directory, or provision a new FTP site profile.
---

# safe-ftp-deploy

A safety-first FTP/FTPS deploy tool, built specifically to be handed to an
AI agent. It enforces its own safety rules regardless of what you ask it to
do: it never deletes anything (the only "destructive" action is renaming
the old file to a timestamped backup), it refuses to overwrite a file that
changed since the tool last touched it (drift detection), it defaults to a
dry run on every write operation, and each site has a directory whitelist
you cannot bypass by asking nicely.

This is why it's safe to drive directly, unlike raw FTP access or an
unrestricted FTP MCP server: **the tool decides what's allowed, not you.**
Your job is to decide *what* to deploy and to follow the workflow below —
not to work around the guardrails.

## How to reach it

**Preferred: MCP tools**, if `safe-ftp-deploy mcp` is configured as an MCP
server in this session. Eight tools, all returning a `summary_markdown`
field — relay that directly to the user instead of composing your own
summary from the raw fields:

| Tool | Purpose |
|---|---|
| `deploy` | Upload a single local file to a remote path |
| `batch_deploy` | Upload every file under a local folder to a remote folder |
| `download` | Download a single remote file to a local path |
| `batch_download` | Download every file under a remote folder to a local folder |
| `status` | Check drift status of a remote file, read-only |
| `history` | Show past deploys for a remote file (timestamp, message, hash, backup), read-only |
| `list_remote` | List a remote directory's contents, read-only |
| `setup_site` | Provision or update an encrypted site profile |

`deploy`/`batch_deploy` accept an optional `message` param, recorded in
`history` when the deploy actually executes successfully. Pass a short note
on *why* when the user gives you one (or it's obvious from their request) —
it's what makes `history` useful for reconciling later. Don't invent a
message when there's nothing meaningful to say; an empty one is fine.

**Fallback: the CLI as a subprocess**, if MCP isn't configured. Always add
`--json` so you get structured output instead of having to scrape text:

```bash
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php --json
```

Either way, `--name`/`name` (which site) is usually omittable — it defaults
to the site recorded in `.ftpconfig` for the current project directory. Only
pass it explicitly when you need to target a different site than the
project's default.

## The required workflow

1. **Dry run first, always.** Every write tool (`deploy`, `batch_deploy`,
   `download`, `batch_download`) defaults to `execute=False` /
   no `--execute` flag. Call it that way first. The dry-run response
   already tells you exactly what *would* happen — including whether the
   file actually differs at all (`no_change`) or is blocked by the site's
   whitelist (`blocked`) — it is not a guess.
2. **Show the result to the user before doing anything further.** For a
   batch operation, relay the `summary_markdown` table as-is: it's already
   grouped so the files that will actually change are listed first, ahead
   of the unchanged/blocked/drift rows, with full local and remote paths
   on every row. Don't summarize it down to "N files ready" — the user
   asked to see what's changing so they can verify it themselves.
3. **Only call again with `execute=True` (or `--execute`) after that
   review**, and only once the user has confirmed it's what they want.
   Never chain a dry run straight into an executed call in the same turn
   without the user seeing the dry run first.
4. **Never pass `force=True` (or `--force`) unless the user explicitly
   tells you to, after they've looked at the drift/stale-download details
   themselves.** A `drift_detected` or `stale_download` result means the
   file changed since this tool (or your own earlier download) last saw
   it — that's the tool protecting against overwriting someone else's
   change, not a bug to route around.
5. **Never invent or guess `allowed_dirs`/whitelist entries to make a
   `blocked` result go away.** If a path is outside the site's configured
   whitelist, that's a deliberate restriction set by the human who ran
   `setup_site` — ask them, don't work around it.
6. **Don't collect FTP passwords in chat.** If no site is configured,
   tell the user to run `safe-ftp-deploy setup-site --name <site>` in
   their own terminal, or to point it at a FileZilla export with
   `--from-filezilla`. Use the `setup_site` tool only when the user has
   deliberately given you every value, and never invent placeholders.
7. **Never turn off TLS verification.** FTPS certificates are verified by
   default. `--insecure-tls` is a human decision made at setup and is not
   exposed through MCP. If a connection fails on certificate
   verification, tell the user and let them decide.

## Editing a file that lives on the server

Download it with `download` and note the `hash` in the result. Edit the
local copy, then call `deploy` with `expected_hash` set to that hash. If
someone changed the server file in between, you get `stale_download` and
nothing is written. Download the current version again and redo the edit.

## Reading results

| Status | What to do |
|---|---|
| `dry_run` | Show the plan, ask the user to confirm |
| `success` | Report it and the backup name |
| `no_change` | Tell the user the files are identical, nothing to do |
| `blocked` | Relay it, ask the user. Don't work around it |
| `drift_detected` | Show both hashes, ask the user. No `force` on your own |
| `stale_download` | Download again, re-apply the edit, deploy again |
| `upload_verification_failed` | Report it. The old file is safe under its backup name. Don't retry blindly |
| `error` | Report the message |

`status` returns `no_history` for a file the tool has never deployed. That
means there is no recorded hash to compare against, not that it is safe.

To undo a deploy, `history` gives the backup name of each one. There is no
rollback command, so tell the user to rename the backup back on the server
in their FTP client.

## Common mistakes to avoid

- Calling `deploy`/`batch_deploy`/etc. with `execute=True` on the very
  first call for a given file, without ever having shown a dry run.
- Treating `blocked` as an error to retry differently rather than a
  deliberate refusal to relay to the user.
- Re-summarizing a batch result instead of relaying its
  `summary_markdown` (which is already built to highlight what matters).
- Setting `force=True` because a `drift_detected`/`stale_download` result
  was inconvenient, instead of surfacing it and asking.
- Asking the user to paste FTP or master passwords into the chat.
