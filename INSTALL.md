# Install and use safe-ftp-deploy (instructions for AI agents)

You are an AI coding agent. A user asked you to install safe-ftp-deploy by reading this file. Follow it top to bottom. Do not skip the rules in section 5.

## 1. What this tool is

`safe-ftp-deploy` deploys and downloads files over FTP or FTPS with guardrails that you cannot turn off:

- It never deletes anything. Replacing a file renames the old one to a timestamped backup.
- It refuses to overwrite a remote file that changed since the tool last touched it (drift detection).
- Every write is a dry run until you pass `execute=True` (MCP) or `--execute` (CLI).
- It only touches remote directories on the site's whitelist, which the human sets.
- Every upload is downloaded again and hash-checked.

It supports FTP and FTPS only. It does not support SFTP.

## 2. Install

Check what exists before installing.

1. Run `safe-ftp-deploy --version`. If it prints a version, skip to step 3.
2. Check for uv with `uv --version`. If missing, tell the user to install it from https://docs.astral.sh/uv/getting-started/installation/ and wait. Do not pipe a remote script into a shell on your own.
3. Install the tool:

```bash
uv tool install git+https://github.com/vivekkushalch/safe_ftp.git
```

4. Run `safe-ftp-deploy --version` again to confirm. If the command is not found, run `uv tool update-shell`, then tell the user to open a new terminal.

No Python on the machine? Use the Docker route in section 8 instead.

## 3. Connect yourself

Work out which agent you are, then run the matching command from the user's project folder. The command merges a server entry into your config file and keeps existing entries.

| You are | Command | MCP config it writes | Guidance it writes |
|---|---|---|---|
| Claude Code | `safe-ftp-deploy install claude` | `.mcp.json` | `.claude/skills/safe-ftp-deploy/SKILL.md` |
| Cursor | `safe-ftp-deploy install cursor` | `.cursor/mcp.json` | `AGENTS.md` |
| Windsurf | `safe-ftp-deploy install windsurf` | `~/.codeium/windsurf/mcp_config.json` (global) | `AGENTS.md` |
| OpenCode | `safe-ftp-deploy install opencode` | `opencode.json` | `AGENTS.md` |
| Antigravity | `safe-ftp-deploy install antigravity` | `.agents/mcp_config.json` | `AGENTS.md` |

Do not run `install all` unless the user asks. It writes config for every agent, including Windsurf's global file.

**Any other agent or MCP client.** Add this server entry to its MCP config by hand. The server speaks MCP over stdio.

```json
{"mcpServers": {"safe-ftp-deploy": {"command": "safe-ftp-deploy", "args": ["mcp"]}}}
```

If your client uses a different config shape, the launch command is `safe-ftp-deploy mcp`. Put the contents of section 5 and 6 into whatever instruction file your client reads (for example `AGENTS.md`, `CLAUDE.md`, or a rules file).

After installing, tell the user to restart you or reload MCP servers. MCP tools do not appear in a session that was already running.

## 4. Save the FTP login (the user does this)

The site profile holds the FTP host, username and password, encrypted with a master password. Ask the user to run this in their own terminal:

```bash
safe-ftp-deploy setup-site --name <site-name>
```

It asks for a master password, FTP host, port, username, password, and the remote directories the tool may touch (for example `/public_html/`). It writes `.ftpconfig` in the project folder, so later commands do not need `--name`.

Do not ask the user to paste FTP or master passwords into the chat. Do not read `.ftpconfig` or `~/.safe_ftp_deploy/`. If the user already has the site in FileZilla, they can run `safe-ftp-deploy setup-site --name <site-name> --from-filezilla ./export.xml` instead.

Tell the user to set the directory whitelist. An empty whitelist allows the whole site.

## 5. Rules you must follow

1. Dry run first, every time. Call write tools with `execute=False` (or no `--execute`) before anything else.
2. Show the user the result. Relay the `summary_markdown` field as it is. Do not shorten it to "N files ready".
3. Call again with `execute=True` only after the user confirms. Never go from dry run to execute in one turn without the user seeing the plan.
4. Never use `force=True` or `--force` unless the user tells you to, after looking at the drift details.
5. If the result is `blocked`, relay it. Do not guess or edit whitelist entries to get around it.
6. Do not turn off TLS verification. `--insecure-tls` is a human decision made at setup time.
7. Pass a short `message` to `deploy` and `batch_deploy` when the user gave a reason. It is saved in the deploy history. Leave it empty if there is no reason.

## 6. How to use it

### MCP tools (preferred)

| Tool | Purpose | Writes |
|---|---|---|
| `deploy` | Upload one file. Args: `local`, `remote`, `name`, `execute`, `force`, `expected_hash`, `message` | yes |
| `batch_deploy` | Upload a folder. Args: `local_dir`, `remote_dir`, `include`, `exclude`, `execute`, `force`, `message` | yes |
| `download` | Download one file. Args: `remote`, `local`, `execute`, `force` | local files |
| `batch_download` | Download a folder. Args: `remote_dir`, `local_dir`, `include`, `exclude`, `execute` | local files |
| `status` | Compare a remote file with its last known hash. Args: `remote` | no |
| `history` | Past deploys of a file. Args: `remote`, `limit` | no |
| `list_remote` | List a remote directory. Args: `remote_dir`, `recursive` | no |
| `setup_site` | Save a site profile. Prefer the terminal route in section 4 | local config |

`name` selects the site and is optional when `.ftpconfig` exists. `include` and `exclude` are comma-separated glob patterns.

### CLI (when MCP is not available)

Add `--json` so you get structured output instead of text to scrape.

```bash
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php --json
safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php --execute --json -m "reason"
safe-ftp-deploy batch-deploy --local-dir ./site --remote-dir /public_html --exclude "vendor/*,*.log" --json
safe-ftp-deploy download --remote /public_html/config.php --local ./config.php --json
safe-ftp-deploy status --remote /public_html/index.php --json
safe-ftp-deploy history --remote /public_html/index.php --json
safe-ftp-deploy list --remote-dir /public_html --recursive --json
```

Run commands from the project folder so the tool finds `.ftpconfig`.

### Typical workflow

1. `status` the remote file if you have not deployed it before. `no_history` means the tool has no recorded hash to compare against.
2. Dry-run the deploy and show the plan.
3. After the user confirms, run it with `execute=True`.
4. Report the status and the backup name from the result.

When editing a file that lives on the server, download it, edit it, then deploy with `expected_hash` set to the hash the download reported. If someone changed the server file in between, you get `stale_download` and nothing is written.

## 7. Reading the results

| Status | What it means | What you do |
|---|---|---|
| `dry_run` | Nothing changed. The message is the plan. | Show it, ask to confirm |
| `success` | Changed and verified | Report the backup name |
| `no_change` | Local and remote are identical | Tell the user, nothing to do |
| `blocked` | Path is outside the whitelist | Relay it, ask the user |
| `drift_detected` | Server file changed since the last deploy | Show the hashes, ask the user. No `force` on your own |
| `stale_download` | Server file differs from your `expected_hash` | Download the current version again, re-apply the edit |
| `upload_verification_failed` | Re-download did not match. The old file is safe under its backup name | Report it, do not retry blindly |
| `download_verification_failed` | Same check for downloads | Report it |
| `error` | Something else, such as a missing local file | Report the message |

To undo a deploy, `history` shows the backup name. Restoring means renaming the backup back on the server in an FTP client. There is no rollback command yet.

## 8. Docker instead of a local install

If the user has Docker and no Python, build the image and run the MCP server over stdio. Credentials live in a named volume.

```bash
docker build -t safe-ftp-deploy https://github.com/vivekkushalch/safe_ftp.git
docker run --rm -it -v safe-ftp-data:/home/app/.safe_ftp_deploy -v "$PWD":/work safe-ftp-deploy setup-site --name <site-name>
```

MCP entry for the container:

```json
{"mcpServers": {"safe-ftp-deploy": {"command": "docker", "args": ["run", "--rm", "-i", "-v", "safe-ftp-data:/home/app/.safe_ftp_deploy", "-v", "/absolute/path/to/project:/work", "safe-ftp-deploy", "mcp"]}}}
```

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| `safe-ftp-deploy: command not found` | Run `uv tool update-shell`, open a new terminal |
| MCP tools are missing | Restart the agent or reload MCP servers. Check the config file from section 3 contains the entry |
| `Could not connect: TLS certificate verification failed` | The host uses a self-signed or mismatched certificate. The user decides whether to re-run `setup-site --insecure-tls` |
| `blocked` on a path you expect to work | The path is not under a whitelisted directory. Ask the user to run `setup-site` again with the right `--allowed-dirs` |
| Wrong site used | Pass `name` explicitly, or run from the project folder that holds `.ftpconfig` |

## 10. Uninstall

```bash
uv tool uninstall safe-ftp-deploy
```

Then remove the `safe-ftp-deploy` entry from the agent config files listed in section 3, and delete `~/.safe_ftp_deploy/` if the user wants the saved logins gone.

## 11. When you are done installing

Tell the user, in a few lines:

1. What you installed and which config files you changed.
2. That they need to restart the agent, and run `safe-ftp-deploy setup-site --name <site-name>` themselves.
3. That every deploy will start as a dry run and you will ask before executing.
