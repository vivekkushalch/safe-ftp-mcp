"""MCP tool logic wrapping safe_ftp's core operations.

Every _X_impl function here is a plain Python function -- no mcp SDK
import, fully testable with the same FakeFTP-double pattern the rest of
this project's tests use. _build_mcp_server()/run_server() (added in a
later task) are the only parts of this module that import the mcp
package, and they do so lazily so `import safe_ftp_mcp` never requires it.

Each function wraps its body in try/except SystemExit -- several of the
safe_ftp functions called here (_load_site_or_exit, the setup-site
resolver chain) signal errors via SystemExit, which is fine for a CLI
process exiting but must never propagate out of a tool call in a
long-running MCP server.
"""

import os
import types

import safe_ftp
import safe_ftp_format as fmt


def _resolve_and_load(name):
    site_name = safe_ftp._resolve_site_name_value(name)
    site = safe_ftp._load_site_or_exit(site_name)
    return site_name, site


def _deploy_impl(local: str = "", remote: str = "", name: str = None, execute: bool = False,
                  force: bool = False, expected_hash: str = None) -> dict:
    try:
        site_name, site = _resolve_and_load(name)
        result = safe_ftp.deploy_file(site_name, site, local, remote, execute=execute, force=force,
                                       expected_hash=expected_hash)
        result["summary_markdown"] = fmt.format_deploy_markdown(result)
        return result
    except SystemExit as e:
        return {"status": "error", "message": str(e)}


def _batch_deploy_impl(local_dir: str = "", remote_dir: str = "", name: str = None,
                        include: str = None, exclude: str = None,
                        execute: bool = False, force: bool = False) -> dict:
    try:
        site_name, site = _resolve_and_load(name)
        include_list = include.split(",") if include else []
        exclude_list = exclude.split(",") if exclude else []
        results = safe_ftp.batch_deploy_files(site_name, site, local_dir, remote_dir,
                                               include=include_list, exclude=exclude_list,
                                               execute=execute, force=force)
        return {
            "results": results,
            "summary_markdown": fmt.format_batch_deploy_markdown(results, local_dir, remote_dir),
        }
    except SystemExit as e:
        return {"status": "error", "message": str(e)}


def _download_impl(remote: str = "", local: str = "", name: str = None,
                    execute: bool = False, force: bool = False) -> dict:
    try:
        site_name, site = _resolve_and_load(name)
        result = safe_ftp.download_file(site_name, site, remote, local, execute=execute, force=force)
        result["summary_markdown"] = fmt.format_download_markdown(result)
        return result
    except SystemExit as e:
        return {"status": "error", "message": str(e)}


def _batch_download_impl(remote_dir: str = "", local_dir: str = "", name: str = None,
                          include: str = None, exclude: str = None,
                          execute: bool = False, force: bool = False) -> dict:
    try:
        site_name, site = _resolve_and_load(name)
        include_list = include.split(",") if include else []
        exclude_list = exclude.split(",") if exclude else []
        results = safe_ftp.batch_download_files(site_name, site, remote_dir, local_dir,
                                                  include=include_list, exclude=exclude_list,
                                                  execute=execute, force=force)
        return {
            "results": results,
            "summary_markdown": fmt.format_batch_download_markdown(results, remote_dir, local_dir),
        }
    except SystemExit as e:
        return {"status": "error", "message": str(e)}


def _status_impl(remote: str = "", name: str = None) -> dict:
    try:
        site_name, site = _resolve_and_load(name)
        result = safe_ftp.check_status(site_name, site, remote)
        result["summary_markdown"] = fmt.format_status_markdown(result)
        return result
    except SystemExit as e:
        return {"status": "error", "message": str(e)}


def _list_remote_impl(remote_dir: str = "", name: str = None, recursive: bool = False,
                       entry_type: str = "all", include: str = None, exclude: str = None,
                       limit: int = None, sort_by: str = "name", reverse: bool = False,
                       max_depth: int = None) -> dict:
    try:
        site_name, site = _resolve_and_load(name)
        include_list = include.split(",") if include else []
        exclude_list = exclude.split(",") if exclude else []
        result = safe_ftp.list_remote_dir(
            site_name, site, remote_dir,
            recursive=recursive, entry_type=entry_type,
            include=include_list, exclude=exclude_list,
            limit=limit, sort_by=sort_by, reverse=reverse, max_depth=max_depth,
        )
        result["summary_markdown"] = fmt.format_list_remote_markdown(result)
        return result
    except SystemExit as e:
        return {"status": "error", "message": str(e)}


def _setup_site_impl(name: str = "", host: str = None, port: str = None, username: str = None,
                      ftp_password: str = None, master_password: str = None,
                      use_tls: bool = None, allowed_dirs: str = None,
                      from_filezilla: str = None) -> dict:
    args = types.SimpleNamespace(
        non_interactive=True,
        master_password=master_password,
        ftp_password=ftp_password,
        host=host,
        port=port,
        username=username,
        use_tls=(use_tls is True),
        no_tls=(use_tls is False),
        allowed_dirs=allowed_dirs,
    )

    try:
        ftpconfig_existed = os.path.exists(safe_ftp._ftpconfig_path())
        masterpwd_existed = os.path.exists(safe_ftp._masterpwd_path())

        imported = {"host": None, "port": None, "username": None, "password": None, "use_tls": None}
        if from_filezilla:
            imported = safe_ftp._parse_filezilla_export(from_filezilla)

        resolved_master_password = safe_ftp._resolve_master_password_for_setup(args)
        sites = (
            safe_ftp._load_all_sites(resolved_master_password)
            if os.path.exists(safe_ftp.CREDS_FILE) else {}
        )

        resolved_host = safe_ftp._resolve_required_field(args.host, imported["host"], "--host", args,
                                                           "FTP host")
        resolved_port = safe_ftp._resolve_port(args, imported["port"])
        resolved_username = safe_ftp._resolve_required_field(args.username, imported["username"],
                                                               "--username", args, "FTP username")
        resolved_password = safe_ftp._resolve_ftp_password_for_setup(args, imported["password"])
        resolved_use_tls = safe_ftp._resolve_use_tls(args, imported["use_tls"])
        resolved_allowed_dirs = safe_ftp._resolve_allowed_dirs(args)

        sites[name] = {
            "host": resolved_host,
            "port": resolved_port,
            "username": resolved_username,
            "password": resolved_password,
            "use_tls": resolved_use_tls,
            "allowed_remote_dirs": resolved_allowed_dirs,
        }
        safe_ftp._save_all_sites(sites, resolved_master_password)

        connection_ok, connection_message = safe_ftp._test_site_connection(sites[name])

        migrated = not ftpconfig_existed and masterpwd_existed
        safe_ftp._write_ftpconfig(name, resolved_master_password)

        result = {
            "site": name,
            "host": resolved_host,
            "port": resolved_port,
            "use_tls": resolved_use_tls,
            "connection_ok": connection_ok,
            "connection_message": connection_message,
            "allowed_remote_dirs": resolved_allowed_dirs,
            "migrated_from_masterpwd": migrated,
            "creds_file": safe_ftp.CREDS_FILE,
        }
        result["summary_markdown"] = fmt.format_setup_site_markdown(result)
        return result
    except SystemExit as e:
        return {"status": "error", "message": str(e)}
