"""Markdown formatting for safe_ftp result dicts.

Pure functions -- no FTP, no file I/O beyond building strings. Used by the
CLI (rendered via rich.markdown.Markdown) and, in a later phase, by the MCP
server (returned as-is in a summary_markdown field for the agent to relay).
"""

_STATUS_ICONS = {
    "success": "✅",
    "dry_run": "\U0001F4DD",
    "no_change": "➖",
    "blocked": "\U0001F6AB",
    "drift_detected": "⚠️",
    "stale_download": "⚠️",
    "upload_verification_failed": "❌",
    "download_verification_failed": "❌",
    "error": "❌",
}

_STATUS_LABELS = {
    "success": "Success",
    "dry_run": "Dry run",
    "no_change": "No change needed",
    "blocked": "Blocked",
    "drift_detected": "Drift detected",
    "stale_download": "Stale download",
    "upload_verification_failed": "Upload verification failed",
    "download_verification_failed": "Download verification failed",
    "error": "Error",
}

_BATCH_GROUP_ORDER = {
    "dry_run": 0,
    "success": 0,
    "no_change": 1,
    "blocked": 2,
    "drift_detected": 3,
    "stale_download": 3,
    "upload_verification_failed": 4,
    "download_verification_failed": 4,
    "error": 4,
}


def _status_icon(status) -> str:
    return _STATUS_ICONS.get(status, "❓")


def _status_label(status) -> str:
    return _STATUS_LABELS.get(status, str(status))


def _human_size(size) -> str:
    """size may be a numeric string (from MLSD facts), an int, or None."""
    if size is None:
        return "-"
    try:
        num = float(size)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def format_deploy_markdown(result: dict) -> str:
    icon = _status_icon(result.get("status"))
    lines = [
        f"### Deploy: `{result.get('local_path')}` → `{result.get('remote_path')}`",
        "",
        f"{icon} **{_status_label(result.get('status'))}** — {result.get('message', '')}",
    ]
    if result.get("backup_name"):
        lines.append(f"- Backup: `{result['backup_name']}`")
    if result.get("status") == "drift_detected":
        lines.append(f"- Last known hash: `{(result.get('last_known_hash') or '')[:8]}`")
        lines.append(f"- Current remote hash: `{(result.get('current_remote_hash') or '')[:8]}`")
    if result.get("status") == "stale_download":
        lines.append(f"- Expected hash: `{(result.get('expected_hash') or '')[:8]}`")
        lines.append(f"- Current remote hash: `{(result.get('current_remote_hash') or '')[:8]}`")
    return "\n".join(lines)


def format_download_markdown(result: dict) -> str:
    icon = _status_icon(result.get("status"))
    lines = [
        f"### Download: `{result.get('remote_path')}` → `{result.get('local_path')}`",
        "",
        f"{icon} **{_status_label(result.get('status'))}** — {result.get('message', '')}",
    ]
    if result.get("local_backup_name"):
        lines.append(f"- Local backup: `{result['local_backup_name']}`")
    if result.get("hash"):
        lines.append(f"- Hash: `{result['hash'][:8]}`")
    return "\n".join(lines)


def format_status_markdown(result: dict) -> str:
    icon = _status_icon(result.get("status"))
    lines = [
        f"### Status: `{result.get('remote_path')}`",
        "",
        f"{icon} **{_status_label(result.get('status'))}** — {result.get('message', '')}",
    ]
    if result.get("current_remote_hash"):
        lines.append(f"- Current remote hash: `{result['current_remote_hash'][:8]}`")
    if result.get("last_known_hash"):
        lines.append(f"- Last known hash: `{result['last_known_hash'][:8]}`")
    return "\n".join(lines)


def _escape_table_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def format_history_markdown(result: dict) -> str:
    lines = [f"### Deploy history: `{result.get('remote_path')}`", ""]
    entries = result.get("entries", [])
    if not entries:
        lines.append("_No recorded deploys for this file yet._")
        return "\n".join(lines)

    lines.append("| When | Message | New hash | Backup |")
    lines.append("|---|---|---|---|")
    for e in entries:
        message = _escape_table_cell(e["message"]) if e.get("message") else "_(no message)_"
        new_hash = (e.get("new_hash") or "")[:8]
        backup = f"`{e['backup_name']}`" if e.get("backup_name") else "-"
        lines.append(f"| {e.get('deployed_at', '')} | {message} | `{new_hash}` | {backup} |")

    total = result.get("total_entries", len(entries))
    lines.append("")
    lines.append(f"Showing {len(entries)} of {total} recorded deploy(s).")
    return "\n".join(lines)


def format_list_remote_markdown(result: dict) -> str:
    lines = [f"### Listing: `{result.get('remote_dir')}`", ""]

    if result.get("status") in ("blocked", "error"):
        lines.append(f"\U0001F6AB {result.get('message', '')}")
        return "\n".join(lines)

    entries = result.get("entries", [])
    if not entries:
        lines.append(f"_{result.get('message', 'No entries.')}_")
        return "\n".join(lines)

    lines.append("| Type | Name | Size | Modified |")
    lines.append("|---|---|---|---|")
    dirs = files = 0
    total_bytes = 0
    for e in entries:
        is_dir = e.get("type") == "dir"
        tag = "\U0001F4C1" if is_dir else "\U0001F4C4"
        if is_dir:
            dirs += 1
        else:
            files += 1
        size = e.get("size")
        if size is not None:
            try:
                total_bytes += int(size)
            except (TypeError, ValueError):
                pass
        label = e.get("path", e.get("name", ""))
        lines.append(f"| {tag} | `{label}` | {_human_size(size)} | {e.get('modify') or '-'} |")

    summary = f"**{len(entries)} entries** — {dirs} dirs, {files} files, {_human_size(total_bytes)} total"
    if result.get("truncated"):
        summary += f" (showing {len(entries)} of {result.get('total_matched')} matched)"
    lines.append("")
    lines.append(summary)
    return "\n".join(lines)


def _format_batch_table(results: list, backup_key: str) -> str:
    """Shared table renderer for batch-deploy/batch-download results.
    Rows are grouped by outcome: would-change first, then unchanged, then
    blocked, then drift/stale, then errors -- so the actionable rows are
    never buried under no-op ones."""
    if not results:
        return "_No files matched the given filters._"

    ordered = sorted(results, key=lambda r: _BATCH_GROUP_ORDER.get(r.get("status"), 5))

    lines = ["| | Local | Remote | Outcome |", "|---|---|---|---|"]
    changed = unchanged = blocked = other = 0
    for r in ordered:
        status = r.get("status")
        icon = _status_icon(status)
        if status in ("dry_run", "success"):
            changed += 1
        elif status == "no_change":
            unchanged += 1
        elif status == "blocked":
            blocked += 1
        else:
            other += 1
        backup = r.get(backup_key)
        outcome = _status_label(status) + (f" (backup: `{backup}`)" if backup else "")
        lines.append(f"| {icon} | `{r.get('local_path', '')}` | `{r.get('remote_path', '')}` | {outcome} |")

    summary_parts = [f"**{changed} file(s) will change**" if changed else "No files will change"]
    if unchanged:
        summary_parts.append(f"{unchanged} unchanged")
    if blocked:
        summary_parts.append(f"{blocked} blocked")
    if other:
        summary_parts.append(f"{other} need review")

    return "\n".join(lines) + "\n\n" + ", ".join(summary_parts)


def format_batch_deploy_markdown(results: list, local_dir: str, remote_dir: str) -> str:
    header = f"### Batch Deploy: `{local_dir}` → `{remote_dir}`\n\n{len(results)} file(s) matched filters."
    return header + "\n\n" + _format_batch_table(results, "backup_name")


def format_batch_download_markdown(results: list, remote_dir: str, local_dir: str) -> str:
    header = f"### Batch Download: `{remote_dir}` → `{local_dir}`\n\n{len(results)} file(s) matched filters."
    return header + "\n\n" + _format_batch_table(results, "local_backup_name")


def format_setup_site_markdown(result: dict) -> str:
    lines = [f"### Site saved: `{result.get('site')}`", ""]
    protocol = "FTPS" if result.get("use_tls") else "FTP"
    lines.append(f"- Host: `{result.get('host')}:{result.get('port')}` ({protocol})")

    if result.get("connection_ok"):
        lines.append(f"- ✅ Connection test: OK — {result.get('connection_message', '')}")
    else:
        lines.append(
            f"- ⚠️ WARNING: connection test failed — {result.get('connection_message', '')} "
            "(site was still saved)"
        )

    allowed_dirs = result.get("allowed_remote_dirs") or []
    if allowed_dirs:
        joined = ", ".join(f"`{d}`" for d in allowed_dirs)
        lines.append(f"- Allowed directories: {joined}")
    else:
        lines.append("- WARNING: no allowed_remote_dirs set -- deploys can target any path.")

    if result.get("migrated_from_masterpwd"):
        lines.append("- Migrated your master password into .ftpconfig — you can delete .masterpwd now.")

    lines.append(f"- Credentials saved to `{result.get('creds_file')}`")
    return "\n".join(lines)
