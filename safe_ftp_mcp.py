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
                  force: bool = False, expected_hash: str = None, message: str = None) -> dict:
    try:
        site_name, site = _resolve_and_load(name)
        result = safe_ftp.deploy_file(site_name, site, local, remote, execute=execute, force=force,
                                       expected_hash=expected_hash, message=message)
        result["summary_markdown"] = fmt.format_deploy_markdown(result)
        return result
    except SystemExit as e:
        return {"status": "error", "message": str(e)}


def _batch_deploy_impl(local_dir: str = "", remote_dir: str = "", name: str = None,
                        include: str = None, exclude: str = None,
                        execute: bool = False, force: bool = False, message: str = None) -> dict:
    try:
        site_name, site = _resolve_and_load(name)
        include_list = include.split(",") if include else []
        exclude_list = exclude.split(",") if exclude else []
        results = safe_ftp.batch_deploy_files(site_name, site, local_dir, remote_dir,
                                               include=include_list, exclude=exclude_list,
                                               execute=execute, force=force, message=message)
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


def _history_impl(remote: str = "", name: str = None, limit: int = 10) -> dict:
    try:
        site_name = safe_ftp._resolve_site_name_value(name)
        result = safe_ftp.get_deploy_history(site_name, remote, limit=limit)
        result["summary_markdown"] = fmt.format_history_markdown(result)
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


def _build_mcp_server():
    """Registers each _X_impl as an MCP tool. Imports the mcp SDK lazily --
    this is the only function in this module that requires it installed.

    Note: the installed mcp SDK (2.0.0+) renamed FastMCP to MCPServer,
    moved to mcp.server.mcpserver -- the constructor and @tool() decorator
    usage are otherwise unchanged from the older FastMCP API."""
    from mcp.server.mcpserver import MCPServer

    mcp_server = MCPServer("safe-ftp")

    @mcp_server.tool()
    def deploy(local: str, remote: str, name: str = None, execute: bool = False,
               force: bool = False, expected_hash: str = None, message: str = None) -> dict:
        """Deploy a single local file to a remote path. Dry-run unless
        execute=True -- always review the dry-run result before setting
        execute=True on a real call. On a successful execute, message is
        recorded in the local deploy history (see the history tool) --
        pass a short note on why the change was made when you have one."""
        return _deploy_impl(local=local, remote=remote, name=name, execute=execute,
                             force=force, expected_hash=expected_hash, message=message)

    @mcp_server.tool()
    def batch_deploy(local_dir: str, remote_dir: str, name: str = None, include: str = None,
                      exclude: str = None, execute: bool = False, force: bool = False,
                      message: str = None) -> dict:
        """Deploy every file under local_dir to its mirrored path under
        remote_dir (filtered by comma-separated include/exclude glob
        patterns). Dry-run unless execute=True. On a successful execute,
        message is recorded in each deployed file's history entry."""
        return _batch_deploy_impl(local_dir=local_dir, remote_dir=remote_dir, name=name,
                                   include=include, exclude=exclude, execute=execute, force=force,
                                   message=message)

    @mcp_server.tool()
    def download(remote: str, local: str, name: str = None, execute: bool = False,
                 force: bool = False) -> dict:
        """Download a single remote file to a local path. Dry-run unless execute=True."""
        return _download_impl(remote=remote, local=local, name=name, execute=execute, force=force)

    @mcp_server.tool()
    def batch_download(remote_dir: str, local_dir: str, name: str = None, include: str = None,
                        exclude: str = None, execute: bool = False, force: bool = False) -> dict:
        """Download every file under remote_dir to its mirrored path under
        local_dir (filtered by comma-separated include/exclude glob
        patterns). Dry-run unless execute=True."""
        return _batch_download_impl(remote_dir=remote_dir, local_dir=local_dir, name=name,
                                     include=include, exclude=exclude, execute=execute, force=force)

    @mcp_server.tool()
    def status(remote: str, name: str = None) -> dict:
        """Check drift status of a remote file without changing anything."""
        return _status_impl(remote=remote, name=name)

    @mcp_server.tool()
    def history(remote: str, name: str = None, limit: int = 10) -> dict:
        """Show past deploys for a remote file, most recent first --
        timestamp, message, resulting hash, and backup name for each. Purely
        local and read-only; does not contact the server."""
        return _history_impl(remote=remote, name=name, limit=limit)

    @mcp_server.tool()
    def list_remote(remote_dir: str, name: str = None, recursive: bool = False,
                     entry_type: str = "all", include: str = None, exclude: str = None,
                     limit: int = None, sort_by: str = "name", reverse: bool = False,
                     max_depth: int = None) -> dict:
        """List a remote directory's contents. Read-only."""
        return _list_remote_impl(remote_dir=remote_dir, name=name, recursive=recursive,
                                  entry_type=entry_type, include=include, exclude=exclude,
                                  limit=limit, sort_by=sort_by, reverse=reverse, max_depth=max_depth)

    @mcp_server.tool()
    def setup_site(name: str, host: str = None, port: str = None, username: str = None,
                    ftp_password: str = None, master_password: str = None, use_tls: bool = None,
                    allowed_dirs: str = None, from_filezilla: str = None) -> dict:
        """Provision or update an encrypted site profile. Every field must
        resolve from a parameter, an environment variable
        (SAFE_FTP_FTP_PASSWORD / SAFE_FTP_MASTER_PASSWORD), an existing
        .ftpconfig, or from_filezilla -- there's no terminal to prompt on."""
        return _setup_site_impl(name=name, host=host, port=port, username=username,
                                 ftp_password=ftp_password, master_password=master_password,
                                 use_tls=use_tls, allowed_dirs=allowed_dirs,
                                 from_filezilla=from_filezilla)

    return mcp_server


def run_server():
    _build_mcp_server().run()
