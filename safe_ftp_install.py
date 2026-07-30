"""Registers safe-ftp-deploy's MCP server (and agent guidance) for various
AI coding agents: Claude Code, Cursor, Windsurf, OpenCode, Antigravity.

Every config write is merge-only: read the existing JSON, set just our
entry, write the rest back untouched. A file that exists but isn't valid
JSON is left alone -- we refuse rather than risk clobbering it.

The skill/AGENTS.md guidance text is embedded here as a constant rather
than read from skill/safe-ftp-deploy/SKILL.md at runtime, because that
file is not currently packaged as installed package data (pyproject.toml
only lists .py modules) -- reading it from disk would break for anyone
who installed via `uv tool install` rather than a git checkout. Keep this
constant in sync with skill/safe-ftp-deploy/SKILL.md by hand; it's short
and changes rarely.
"""

import json
import os

_MCP_ENTRY_STDIO = {"command": "safe-ftp-deploy", "args": ["mcp"]}

SKILL_MD_CONTENT = """\
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
server in this session. Seven tools, all returning a `summary_markdown`
field — relay that directly to the user instead of composing your own
summary from the raw fields:

| Tool | Purpose |
|---|---|
| `deploy` | Upload a single local file to a remote path |
| `batch_deploy` | Upload every file under a local folder to a remote folder |
| `download` | Download a single remote file to a local path |
| `batch_download` | Download every file under a remote folder to a local folder |
| `status` | Check drift status of a remote file, read-only |
| `list_remote` | List a remote directory's contents, read-only |
| `setup_site` | Provision or update an encrypted site profile |

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
6. **`setup_site` needs real values for every field** (host, username,
   password, etc.) since there's no terminal to prompt on. If you don't
   have the FTP credentials, ask the user rather than inventing
   placeholders. Prefer pointing at a FileZilla export
   (`from_filezilla`) over asking the user to retype credentials they've
   already saved elsewhere, when one is available.

## Common mistakes to avoid

- Calling `deploy`/`batch_deploy`/etc. with `execute=True` on the very
  first call for a given file, without ever having shown a dry run.
- Treating `blocked` as an error to retry differently rather than a
  deliberate refusal to relay to the user.
- Re-summarizing a batch result instead of relaying its
  `summary_markdown` (which is already built to highlight what matters).
- Setting `force=True` because a `drift_detected`/`stale_download` result
  was inconvenient, instead of surfacing it and asking.
"""

_AGENTS_MD_BEGIN = "<!-- BEGIN safe-ftp-deploy agent guidance (managed by `safe-ftp-deploy install`) -->"
_AGENTS_MD_END = "<!-- END safe-ftp-deploy agent guidance -->"

_AGENTS_MD_BODY = """\
## safe-ftp-deploy

A safety-first FTP/FTPS deploy tool available as MCP tools (`deploy`,
`batch_deploy`, `download`, `batch_download`, `status`, `list_remote`,
`setup_site`) or as the `safe-ftp-deploy` CLI with `--json`. It enforces
its own safety rules regardless of what you ask it to do: no delete
capability, drift detection against the last known server state, a
per-site directory whitelist, and dry-run by default on every write.

Required workflow:
1. Every write tool defaults to `execute=False` (no `--execute`) --
   call it that way first and show the dry-run result to the user.
2. Relay a batch operation's `summary_markdown` field as-is -- it's
   already grouped so files that will actually change are listed first.
3. Only call again with `execute=True`/`--execute` after the user has
   reviewed the dry run and confirmed.
4. Never pass `force=True`/`--force` unless the user explicitly says to,
   after seeing the drift/stale-download details themselves.
5. Never invent `allowed_dirs` entries to work around a `blocked` result --
   that whitelist is a deliberate restriction, ask the user instead.
"""


def _read_json_file(path: str) -> dict:
    """Read a JSON object from path. Returns {} if missing. Raises
    ValueError if it exists but isn't valid JSON -- callers must never
    overwrite a file they couldn't parse."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} exists but isn't valid JSON ({e}); please fix it by hand before running install.")


def _write_json_file(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _merge_top_level_entry(path: str, top_key: str, server_name: str, entry: dict) -> str:
    """Read path's JSON, ensure data[top_key] exists as a dict, set
    data[top_key][server_name] = entry, write back. Returns "created",
    "updated", or "unchanged"."""
    data = _read_json_file(path)
    servers = data.setdefault(top_key, {})
    if not isinstance(servers, dict):
        raise ValueError(f"{path}'s '{top_key}' key exists but isn't an object; please fix it by hand.")
    existing = servers.get(server_name)
    if existing == entry:
        return "unchanged"
    action = "updated" if server_name in servers else "created"
    servers[server_name] = entry
    _write_json_file(path, data)
    return action


def install_claude(cwd: str = None) -> dict:
    cwd = cwd or os.getcwd()
    path = os.path.join(cwd, ".mcp.json")
    entry = {"type": "stdio", **_MCP_ENTRY_STDIO}
    try:
        action = _merge_top_level_entry(path, "mcpServers", "safe-ftp-deploy", entry)
    except ValueError as e:
        return {"status": "error", "path": path, "message": str(e)}
    return {"status": "ok", "path": path, "action": action, "message": f"MCP server entry {action} in {path}"}


def install_claude_skill(cwd: str = None) -> dict:
    cwd = cwd or os.getcwd()
    skill_dir = os.path.join(cwd, ".claude", "skills", "safe-ftp-deploy")
    os.makedirs(skill_dir, exist_ok=True)
    path = os.path.join(skill_dir, "SKILL.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(SKILL_MD_CONTENT)
    return {"status": "ok", "path": path, "action": "written", "message": f"Skill written to {path}"}


def install_cursor(cwd: str = None) -> dict:
    cwd = cwd or os.getcwd()
    path = os.path.join(cwd, ".cursor", "mcp.json")
    try:
        action = _merge_top_level_entry(path, "mcpServers", "safe-ftp-deploy", dict(_MCP_ENTRY_STDIO))
    except ValueError as e:
        return {"status": "error", "path": path, "message": str(e)}
    return {"status": "ok", "path": path, "action": action, "message": f"MCP server entry {action} in {path}"}


def install_windsurf() -> dict:
    """Windsurf only supports a global MCP config -- no project-level
    override exists, unlike the other agents here."""
    path = os.path.join(os.path.expanduser("~"), ".codeium", "windsurf", "mcp_config.json")
    try:
        action = _merge_top_level_entry(path, "mcpServers", "safe-ftp-deploy", dict(_MCP_ENTRY_STDIO))
    except ValueError as e:
        return {"status": "error", "path": path, "message": str(e)}
    return {"status": "ok", "path": path, "action": action, "message": f"MCP server entry {action} in {path}"}


def install_antigravity(cwd: str = None) -> dict:
    cwd = cwd or os.getcwd()
    path = os.path.join(cwd, ".agents", "mcp_config.json")
    try:
        action = _merge_top_level_entry(path, "mcpServers", "safe-ftp-deploy", dict(_MCP_ENTRY_STDIO))
    except ValueError as e:
        return {"status": "error", "path": path, "message": str(e)}
    return {"status": "ok", "path": path, "action": action, "message": f"MCP server entry {action} in {path}"}


def install_opencode(cwd: str = None) -> dict:
    cwd = cwd or os.getcwd()
    path = os.path.join(cwd, "opencode.json")
    entry = {"type": "local", "command": ["safe-ftp-deploy", "mcp"], "enabled": True}
    try:
        action = _merge_top_level_entry(path, "mcp", "safe-ftp-deploy", entry)
    except ValueError as e:
        return {"status": "error", "path": path, "message": str(e)}
    return {"status": "ok", "path": path, "action": action, "message": f"MCP server entry {action} in {path}"}


def install_agents_md(cwd: str = None) -> dict:
    cwd = cwd or os.getcwd()
    path = os.path.join(cwd, "AGENTS.md")
    existing = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()

    block = f"{_AGENTS_MD_BEGIN}\n\n{_AGENTS_MD_BODY.strip()}\n\n{_AGENTS_MD_END}"

    if _AGENTS_MD_BEGIN in existing and _AGENTS_MD_END in existing:
        start = existing.index(_AGENTS_MD_BEGIN)
        end = existing.index(_AGENTS_MD_END) + len(_AGENTS_MD_END)
        new_content = existing[:start] + block + existing[end:]
        action = "updated"
    elif existing:
        new_content = existing.rstrip("\n") + "\n\n" + block + "\n"
        action = "appended"
    else:
        new_content = block + "\n"
        action = "created"

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return {"status": "ok", "path": path, "action": action, "message": f"Agent guidance {action} in {path}"}


_TARGETS = {
    "claude": lambda cwd: [install_claude(cwd), install_claude_skill(cwd)],
    "cursor": lambda cwd: [install_cursor(cwd), install_agents_md(cwd)],
    "windsurf": lambda cwd: [install_windsurf(), install_agents_md(cwd)],
    "opencode": lambda cwd: [install_opencode(cwd), install_agents_md(cwd)],
    "antigravity": lambda cwd: [install_antigravity(cwd), install_agents_md(cwd)],
}


def install_agent(target: str, cwd: str = None) -> list:
    if target == "all":
        results = []
        for name in ("claude", "cursor", "windsurf", "opencode", "antigravity"):
            results.extend(_TARGETS[name](cwd))
        return results
    if target not in _TARGETS:
        raise SystemExit(
            f"Unknown install target '{target}'. Choose from: "
            "claude, cursor, windsurf, opencode, antigravity, all."
        )
    return _TARGETS[target](cwd)
