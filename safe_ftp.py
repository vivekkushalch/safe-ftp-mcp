#!/usr/bin/env python3
"""
safe_ftp_deploy.py
==================

A safety-first deployment tool for Hostinger-style shared FTP hosting.

It mimics the manual workflow you already use:
    1. Look at the file currently on the server.
    2. Rename it to a timestamped backup (e.g. index.php -> index_270726_143210_482391.php).
    3. Upload the new local version in its place.

On top of that, it adds guardrails an AI agent (or a tired human) can rely on:

  - NEVER deletes anything. The only "destructive" action is a rename, and the
    original bytes always continue to exist on the server under the new name.
  - Detects "server drift": if the file on the server has changed since the
    last time this tool touched it (e.g. someone edited it directly on the
    server, or a teammate deployed something you don't know about), it
    refuses to proceed and shows you a diff instead of blindly overwriting.
  - Dry-run by default. Nothing is written anywhere unless you pass --execute.
  - Credentials are encrypted at rest with a password you supply at runtime;
    the password itself is never stored on disk.
  - A per-site "allowed directories" whitelist, so even a misbehaving script
    or agent cannot push files outside the folders you've approved.
  - JSON output mode (--json) so an AI agent can parse results reliably
    instead of scraping printed text.

RECOMMENDED WAY TO USE THIS WITH AN AI CODING AGENT / MCP:
  Do NOT give the agent raw FTP credentials or an FTP MCP tool with unrestricted
  access. Instead, let the agent call this script as a subprocess (or wrap it
  as a single MCP tool) using the --json flag. The agent can decide *what* to
  deploy, but this script -- not the agent -- decides *how*, and it will
  refuse unsafe actions on its own regardless of what the agent asks for.

USAGE
-----
  # One-time setup per site (prompts for host/user/password interactively,
  # nothing is ever typed on the command line where it could end up in shell history)
  python3 safe_ftp_deploy.py setup-site --name mysite

  # See what WOULD happen (default, no changes made)
  python3 safe_ftp_deploy.py deploy --name mysite --local ./index.php --remote /public_html/index.php

  # Actually perform the backup-rename + upload
  python3 safe_ftp_deploy.py deploy --name mysite --local ./index.php --remote /public_html/index.php --execute

  # Deploy a whole folder the same way
  python3 safe_ftp_deploy.py batch-deploy --name mysite --local-dir ./site --remote-dir /public_html --execute

  # Check status / drift for a file without deploying anything
  python3 safe_ftp_deploy.py status --name mysite --remote /public_html/index.php

  # Machine-readable output for an agent
  python3 safe_ftp_deploy.py deploy --name mysite --local ./index.php --remote /public_html/index.php --json
"""

import argparse
import base64
import fnmatch
import getpass
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from ftplib import FTP, FTP_TLS, error_perm

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# File locations (all local, next to this script's working directory)
# ---------------------------------------------------------------------------
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".safe_ftp_deploy")
CREDS_FILE = os.path.join(CONFIG_DIR, "sites.enc")
SALT_FILE = os.path.join(CONFIG_DIR, "salt.bin")
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")  # no secrets in here, just hashes

# .ftpconfig (site name + master password) and legacy .masterpwd (password
# only) are both resolved from the current working directory -- the tool is
# one shared global install now, so cwd is what makes these project-specific.
# This trades away the "password never touches disk" guarantee -- only use
# .ftpconfig/.masterpwd if you've accepted that tradeoff. Never commit or
# back these files up anywhere.
def _ftpconfig_path() -> str:
    return os.path.join(os.getcwd(), ".ftpconfig")


def _masterpwd_path() -> str:
    return os.path.join(os.getcwd(), ".masterpwd")


def _read_ftpconfig():
    """Return (site_name, master_password) from .ftpconfig in the current
    directory. Either or both are None if the file or a given line is
    missing/empty."""
    path = _ftpconfig_path()
    if not os.path.exists(path):
        return None, None
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    site_name = lines[0].strip() if len(lines) >= 1 and lines[0].strip() else None
    password = lines[1].strip() if len(lines) >= 2 and lines[1].strip() else None
    return site_name, password


def _ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------
def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _get_salt() -> bytes:
    _ensure_config_dir()
    if os.path.exists(SALT_FILE):
        with open(SALT_FILE, "rb") as f:
            return f.read()
    salt = os.urandom(16)
    with open(SALT_FILE, "wb") as f:
        f.write(salt)
    return salt


def _load_all_sites(master_password: str) -> dict:
    """Decrypt and return the dict of all site configs. Empty dict if none exist yet."""
    if not os.path.exists(CREDS_FILE):
        return {}
    salt = _get_salt()
    key = _derive_key(master_password, salt)
    fernet = Fernet(key)
    with open(CREDS_FILE, "rb") as f:
        token = f.read()
    try:
        plaintext = fernet.decrypt(token)
    except InvalidToken:
        raise SystemExit("ERROR: wrong master password, or credentials file is corrupted.")
    return json.loads(plaintext.decode("utf-8"))


def _save_all_sites(sites: dict, master_password: str):
    _ensure_config_dir()
    salt = _get_salt()
    key = _derive_key(master_password, salt)
    fernet = Fernet(key)
    token = fernet.encrypt(json.dumps(sites).encode("utf-8"))
    with open(CREDS_FILE, "wb") as f:
        f.write(token)
    # Lock the file down as much as the OS allows (best-effort on non-POSIX)
    try:
        os.chmod(CREDS_FILE, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# State (hash history) helpers -- these track "last known good" remote hash
# so we can detect if someone/something changed the file on the server
# without going through this tool.
# ---------------------------------------------------------------------------
def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def _save_state(state: dict):
    _ensure_config_dir()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _state_key(site_name: str, remote_path: str) -> str:
    return f"{site_name}:{remote_path}"


# ---------------------------------------------------------------------------
# FTP helpers
# ---------------------------------------------------------------------------
def _connect(site: dict) -> FTP:
    if site.get("use_tls", True):
        ftp = FTP_TLS()
        ftp.connect(site["host"], int(site.get("port", 21)), timeout=30)
        ftp.login(site["username"], site["password"])
        ftp.prot_p()  # secure the data channel too
    else:
        ftp = FTP()
        ftp.connect(site["host"], int(site.get("port", 21)), timeout=30)
        ftp.login(site["username"], site["password"])
    return ftp


def _remote_file_exists(ftp: FTP, remote_path: str) -> bool:
    directory, filename = os.path.split(remote_path)
    try:
        listing = ftp.nlst(directory or ".")
    except error_perm:
        return False
    names = [os.path.basename(x) for x in listing]
    return filename in names


def _download_to_temp(ftp: FTP, remote_path: str) -> str:
    """Download remote_path to a local temp file and return its path."""
    fd, tmp_path = tempfile.mkstemp(prefix="ftpdeploy_")
    os.close(fd)
    with open(tmp_path, "wb") as f:
        ftp.retrbinary(f"RETR {remote_path}", f.write)
    return tmp_path


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _backup_timestamp() -> str:
    """
    DDMMYY_HHMMSS_microseconds -- e.g. 270726_143210_482391
    Microseconds are included so that multiple files backed up within the
    same second (common during batch-deploy/batch-download loops) never
    collide on filename.
    """
    return datetime.now().strftime("%d%m%y_%H%M%S_%f")


def _is_within_allowed_dirs(remote_path: str, allowed_dirs: list) -> bool:
    if not allowed_dirs:
        # No whitelist configured -- allow, but this is discouraged; setup-site
        # will nudge the user to set one.
        return True
    norm = os.path.normpath(remote_path)
    for allowed in allowed_dirs:
        if norm.startswith(os.path.normpath(allowed)):
            return True
    return False


def _matches_filters(rel_path: str, include: list, exclude: list) -> bool:
    """rel_path uses forward slashes, relative to the batch root."""
    if exclude:
        for pattern in exclude:
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(os.path.basename(rel_path), pattern):
                return False
    if include:
        return any(
            fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(os.path.basename(rel_path), pattern)
            for pattern in include
        )
    return True


def _walk_remote_dir(ftp: FTP, remote_dir: str):
    """
    Recursively yield remote file paths under remote_dir using MLSD (works on
    Hostinger and most modern FTP servers). Falls back to non-recursive NLST
    if MLSD isn't supported.
    """
    try:
        entries = list(ftp.mlsd(remote_dir))
    except Exception:
        # Fallback: flat listing only, treat everything as a file
        for name in ftp.nlst(remote_dir):
            yield name
        return

    for name, facts in entries:
        if name in (".", ".."):
            continue
        full_path = f"{remote_dir.rstrip('/')}/{name}"
        if facts.get("type") == "dir":
            yield from _walk_remote_dir(ftp, full_path)
        else:
            yield full_path


# ---------------------------------------------------------------------------
# Core safe-deploy logic
# ---------------------------------------------------------------------------
def deploy_file(site_name: str, site: dict, local_path: str, remote_path: str,
                 execute: bool, force: bool = False) -> dict:
    """
    Perform (or simulate) the backup-rename-then-upload flow for one file.
    Returns a structured result dict -- never raises for "expected" problems,
    so callers (including an agent) always get a clean JSON-able result.
    """
    result = {
        "site": site_name,
        "local_path": local_path,
        "remote_path": remote_path,
        "executed": False,
        "status": None,
        "message": "",
        "backup_name": None,
    }

    if not os.path.exists(local_path):
        result["status"] = "error"
        result["message"] = f"Local file does not exist: {local_path}"
        return result

    if not _is_within_allowed_dirs(remote_path, site.get("allowed_remote_dirs", [])):
        result["status"] = "blocked"
        result["message"] = (
            f"Remote path {remote_path} is outside this site's allowed_remote_dirs "
            f"whitelist. Refusing to touch it. Edit the site config to allow it."
        )
        return result

    local_hash = _sha256_of_file(local_path)

    ftp = _connect(site)
    try:
        exists = _remote_file_exists(ftp, remote_path)
        state = _load_state()
        key = _state_key(site_name, remote_path)
        last_known = state.get(key)

        if exists:
            tmp_remote_copy = _download_to_temp(ftp, remote_path)
            try:
                current_remote_hash = _sha256_of_file(tmp_remote_copy)
            finally:
                os.remove(tmp_remote_copy)

            if current_remote_hash == local_hash:
                result["status"] = "no_change"
                result["message"] = "Local and remote files are already identical. Nothing to do."
                return result

            if last_known is not None and current_remote_hash != last_known["hash"] and not force:
                result["status"] = "drift_detected"
                result["message"] = (
                    "The file on the server has changed since the last deploy through this "
                    "tool (someone may have edited it directly on the server, or another "
                    "deploy happened outside this history). Refusing to overwrite. "
                    "Review the server's current version manually, or re-run with --force "
                    "once you're sure it's safe to overwrite."
                )
                result["last_known_hash"] = last_known["hash"]
                result["current_remote_hash"] = current_remote_hash
                return result
        else:
            current_remote_hash = None

        # Compute what the backup name would be. Remote paths are always
        # POSIX-style regardless of the client OS, so build this with plain
        # string concatenation -- os.path.join would insert a backslash on
        # Windows and corrupt the path sent to the FTP server.
        timestamp = _backup_timestamp()
        directory, filename = os.path.split(remote_path)
        name, ext = os.path.splitext(filename)
        backup_name = f"{name}_{timestamp}{ext}"
        backup_path = (directory.rstrip('/') + '/' + backup_name) if directory else backup_name
        result["backup_name"] = backup_path

        if not execute:
            result["status"] = "dry_run"
            if exists:
                result["message"] = (
                    f"[DRY RUN] Would rename remote '{remote_path}' -> '{backup_path}', "
                    f"then upload local '{local_path}' as '{remote_path}'. "
                    f"Re-run with --execute to apply."
                )
            else:
                result["message"] = (
                    f"[DRY RUN] Remote file does not exist yet. Would upload local "
                    f"'{local_path}' as new file '{remote_path}' (no backup needed). "
                    f"Re-run with --execute to apply."
                )
            return result

        # --- Actual execution below. Rename first (this IS the backup step). ---
        if exists:
            ftp.rename(remote_path, backup_path)

        with open(local_path, "rb") as f:
            ftp.storbinary(f"STOR {remote_path}", f)

        # Verify upload by re-downloading and hashing -- don't just trust it worked
        tmp_check = _download_to_temp(ftp, remote_path)
        try:
            uploaded_hash = _sha256_of_file(tmp_check)
        finally:
            os.remove(tmp_check)

        if uploaded_hash != local_hash:
            result["status"] = "upload_verification_failed"
            result["message"] = (
                "Upload completed but the remote file's hash does not match the local "
                "file after re-download. The old version is still safely backed up as "
                f"'{backup_path}'. Please investigate before deploying again."
            )
            return result

        state[key] = {"hash": uploaded_hash, "deployed_at": datetime.now().isoformat()}
        _save_state(state)

        result["executed"] = True
        result["status"] = "success"
        result["message"] = (
            f"Backed up old file to '{backup_path}' and uploaded new version to "
            f"'{remote_path}'. Verified upload integrity."
            if exists else
            f"Uploaded new file to '{remote_path}' (no prior file existed, no backup needed)."
        )
        return result

    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


def download_file(site_name: str, site: dict, remote_path: str, local_path: str,
                    execute: bool, force: bool = False) -> dict:
    """
    Download a remote file to a local path, backing up any existing local
    file first (mirror image of deploy_file's upload safety). Never deletes
    the old local file -- renames it to a timestamped backup instead.
    """
    result = {
        "site": site_name,
        "remote_path": remote_path,
        "local_path": local_path,
        "executed": False,
        "status": None,
        "message": "",
        "local_backup_name": None,
    }

    if not _is_within_allowed_dirs(remote_path, site.get("allowed_remote_dirs", [])):
        result["status"] = "blocked"
        result["message"] = f"Remote path {remote_path} is outside this site's allowed_remote_dirs whitelist."
        return result

    ftp = _connect(site)
    try:
        if not _remote_file_exists(ftp, remote_path):
            result["status"] = "error"
            result["message"] = f"Remote file does not exist: {remote_path}"
            return result

        tmp_remote_copy = _download_to_temp(ftp, remote_path)
        try:
            remote_hash = _sha256_of_file(tmp_remote_copy)

            local_exists = os.path.exists(local_path)
            if local_exists:
                local_hash = _sha256_of_file(local_path)
                if local_hash == remote_hash:
                    result["status"] = "no_change"
                    result["message"] = "Local and remote files are already identical. Nothing to do."
                    return result

                state = _load_state()
                key = _state_key(site_name, remote_path) + ":local"
                last_known = state.get(key)
                if last_known is not None and local_hash != last_known["hash"] and not force:
                    result["status"] = "drift_detected"
                    result["message"] = (
                        "Your local file has changed since the last time this tool downloaded it "
                        "(you may have edited it locally). Refusing to overwrite it. Re-run with "
                        "--force once you're sure it's safe, or back it up yourself first."
                    )
                    return result

            timestamp = _backup_timestamp()
            base, ext = os.path.splitext(local_path)
            backup_path = f"{base}_{timestamp}{ext}"
            result["local_backup_name"] = backup_path if local_exists else None

            if not execute:
                result["status"] = "dry_run"
                if local_exists:
                    result["message"] = (
                        f"[DRY RUN] Would back up local '{local_path}' -> '{backup_path}', "
                        f"then download remote '{remote_path}' to '{local_path}'. "
                        f"Re-run with --execute to apply."
                    )
                else:
                    result["message"] = (
                        f"[DRY RUN] Would download remote '{remote_path}' to new local file "
                        f"'{local_path}' (no local file exists yet, no backup needed)."
                    )
                return result

            os.makedirs(os.path.dirname(os.path.abspath(local_path)) or ".", exist_ok=True)
            if local_exists:
                os.rename(local_path, backup_path)
            # Copy the already-downloaded temp file into place instead of re-downloading
            with open(tmp_remote_copy, "rb") as src, open(local_path, "wb") as dst:
                dst.write(src.read())

            downloaded_hash = _sha256_of_file(local_path)
            if downloaded_hash != remote_hash:
                result["status"] = "download_verification_failed"
                result["message"] = "Downloaded file's hash doesn't match the server copy. Please retry."
                return result

            state = _load_state()
            state[_state_key(site_name, remote_path) + ":local"] = {
                "hash": downloaded_hash, "deployed_at": datetime.now().isoformat()
            }
            _save_state(state)

            result["executed"] = True
            result["status"] = "success"
            result["message"] = (
                f"Backed up old local file to '{backup_path}' and downloaded '{remote_path}' to "
                f"'{local_path}'."
                if local_exists else
                f"Downloaded '{remote_path}' to new local file '{local_path}'."
            )
            return result
        finally:
            os.remove(tmp_remote_copy)
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


def check_status(site_name: str, site: dict, remote_path: str) -> dict:
    """Report drift status for a remote file without changing anything."""
    result = {"site": site_name, "remote_path": remote_path}
    ftp = _connect(site)
    try:
        exists = _remote_file_exists(ftp, remote_path)
        result["remote_exists"] = exists
        if not exists:
            result["status"] = "no_remote_file"
            return result
        tmp = _download_to_temp(ftp, remote_path)
        try:
            current_hash = _sha256_of_file(tmp)
        finally:
            os.remove(tmp)
        result["current_remote_hash"] = current_hash
        state = _load_state()
        last_known = state.get(_state_key(site_name, remote_path))
        if last_known is None:
            result["status"] = "no_history"
            result["message"] = "This tool has no record of previously deploying this file."
        elif last_known["hash"] == current_hash:
            result["status"] = "clean"
            result["message"] = "Remote file matches the last known deploy. Safe to deploy over."
        else:
            result["status"] = "drift"
            result["message"] = "Remote file has changed since the last deploy through this tool."
            result["last_known_hash"] = last_known["hash"]
        return result
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


def list_remote_dir(site_name: str, site: dict, remote_dir: str, recursive: bool = False) -> dict:
    """List a remote directory's contents. Read-only -- makes no changes."""
    result = {"site": site_name, "remote_dir": remote_dir, "entries": []}

    if not _is_within_allowed_dirs(remote_dir, site.get("allowed_remote_dirs", [])):
        result["status"] = "blocked"
        result["message"] = (
            f"Remote path {remote_dir} is outside this site's allowed_remote_dirs "
            f"whitelist. Refusing to list it. Edit the site config to allow it."
        )
        return result

    ftp = _connect(site)
    try:
        if recursive:
            for full_path in _walk_remote_dir(ftp, remote_dir):
                result["entries"].append({"path": full_path, "type": "file"})
            result["status"] = "ok"
            result["message"] = f"{len(result['entries'])} file(s) found under {remote_dir} (recursive)."
            return result

        try:
            entries = list(ftp.mlsd(remote_dir))
        except Exception:
            # Server doesn't support MLSD -- fall back to a flat NLST with no
            # type/size/modify info.
            names = ftp.nlst(remote_dir)
            for n in sorted(names, key=lambda x: os.path.basename(x).lower()):
                result["entries"].append({"name": os.path.basename(n), "type": "?"})
            result["status"] = "ok_flat"
            result["message"] = "Server doesn't support MLSD -- showing a flat listing with no type/size/date."
            return result

        listed = []
        for name, facts in entries:
            if name in (".", ".."):
                continue
            listed.append({
                "name": name,
                "type": facts.get("type", "?"),
                "size": facts.get("size"),
                "modify": facts.get("modify"),
            })
        listed.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        result["entries"] = listed
        result["status"] = "ok"
        result["message"] = f"{len(listed)} entr{'y' if len(listed) == 1 else 'ies'} in {remote_dir}."
        return result
    except error_perm as e:
        result["status"] = "error"
        result["message"] = f"FTP error listing {remote_dir}: {e}"
        return result
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _get_master_password(prompt):
    """Resolve the master password: .ftpconfig (line 2) in the current
    directory, else legacy .masterpwd in the current directory, else an
    interactive getpass prompt."""
    _, ftpconfig_password = _read_ftpconfig()
    if ftpconfig_password:
        print(f"(using master password from {_ftpconfig_path()})", file=sys.stderr)
        return ftpconfig_password

    masterpwd_path = _masterpwd_path()
    if os.path.exists(masterpwd_path):
        with open(masterpwd_path, "r", encoding="utf-8") as f:
            pw = f.read().strip()
        if pw:
            print(f"(using master password from {masterpwd_path})", file=sys.stderr)
            return pw

    return getpass.getpass(prompt)


def cmd_setup_site(args):
    master_password = _get_master_password("Master password to encrypt/decrypt your site credentials: ")
    sites = _load_all_sites(master_password) if os.path.exists(CREDS_FILE) else {}

    host = input("FTP host (e.g. ftp.yourdomain.com): ").strip()
    port = input("FTP port [21]: ").strip() or "21"
    username = input("FTP username: ").strip()
    password = getpass.getpass("FTP password: ")
    use_tls_in = input("Use FTPS/TLS if supported? [Y/n]: ").strip().lower()
    use_tls = use_tls_in != "n"
    allowed = input(
        "Comma-separated list of remote directories this site is allowed to touch "
        "(e.g. /public_html/,/public_html/blog/) [leave blank to allow anywhere -- not recommended]: "
    ).strip()
    allowed_dirs = [d.strip() for d in allowed.split(",") if d.strip()]

    sites[args.name] = {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "use_tls": use_tls,
        "allowed_remote_dirs": allowed_dirs,
    }
    _save_all_sites(sites, master_password)
    print(f"Saved encrypted credentials for site '{args.name}' to {CREDS_FILE}")
    if not allowed_dirs:
        print("WARNING: no allowed_remote_dirs set for this site -- deploys can target any path. "
              "Consider re-running setup-site to restrict this.")


def _load_site_or_exit(name: str) -> dict:
    master_password = _get_master_password("Master password: ")
    sites = _load_all_sites(master_password)
    if name not in sites:
        raise SystemExit(f"No site named '{name}' found. Run setup-site first.")
    return sites[name]


def cmd_deploy(args):
    site = _load_site_or_exit(args.name)
    result = deploy_file(args.name, site, args.local, args.remote, execute=args.execute, force=args.force)
    _print_result(result, args.json)


def cmd_batch_deploy(args):
    site = _load_site_or_exit(args.name)
    include = args.include.split(",") if args.include else []
    exclude = args.exclude.split(",") if args.exclude else []
    results = []
    for root, _dirs, files in os.walk(args.local_dir):
        for fname in files:
            local_full = os.path.join(root, fname)
            rel = os.path.relpath(local_full, args.local_dir).replace(os.sep, "/")
            if not _matches_filters(rel, include, exclude):
                continue
            remote_full = os.path.join(args.remote_dir, rel).replace(os.sep, "/")
            results.append(deploy_file(args.name, site, local_full, remote_full,
                                        execute=args.execute, force=args.force))
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"{len(results)} file(s) matched filters.")
        for r in results:
            _print_result(r, False)


def cmd_download(args):
    site = _load_site_or_exit(args.name)
    result = download_file(args.name, site, args.remote, args.local, execute=args.execute, force=args.force)
    _print_result(result, args.json)


def cmd_batch_download(args):
    site = _load_site_or_exit(args.name)
    include = args.include.split(",") if args.include else []
    exclude = args.exclude.split(",") if args.exclude else []
    ftp = _connect(site)
    try:
        remote_files = list(_walk_remote_dir(ftp, args.remote_dir))
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()

    results = []
    for remote_full in remote_files:
        rel = os.path.relpath(remote_full, args.remote_dir).replace(os.sep, "/")
        if not _matches_filters(rel, include, exclude):
            continue
        local_full = os.path.join(args.local_dir, rel)
        results.append(download_file(args.name, site, remote_full, local_full,
                                      execute=args.execute, force=args.force))
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"{len(results)} file(s) matched filters.")
        for r in results:
            _print_result(r, False)


def cmd_status(args):
    site = _load_site_or_exit(args.name)
    result = check_status(args.name, site, args.remote)
    _print_result(result, args.json)


def cmd_list(args):
    site = _load_site_or_exit(args.name)
    result = list_remote_dir(args.name, site, args.remote_dir, recursive=args.recursive)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    status = result.get("status", "unknown")
    print(f"[{status.upper()}] {result.get('message', '')}")
    for e in result.get("entries", []):
        if "path" in e:
            print(f"  {e['path']}")
        else:
            tag = "DIR " if e.get("type") == "dir" else "file"
            size = e.get("size")
            size_s = f"{size:>10}" if size is not None else " " * 10
            print(f"  [{tag}] {size_s}  {e['name']}")


def _print_result(result: dict, as_json: bool):
    if as_json:
        print(json.dumps(result, indent=2))
        return
    status = result.get("status", "unknown")
    print(f"[{status.upper()}] {result.get('message', '')}")


def main():
    parser = argparse.ArgumentParser(description="Safety-first FTP deploy tool.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup-site", help="Add or update an encrypted site profile.")
    p_setup.add_argument("--name", required=True)
    p_setup.set_defaults(func=cmd_setup_site)

    p_deploy = sub.add_parser("deploy", help="Deploy a single file (dry-run unless --execute).")
    p_deploy.add_argument("--name", required=True)
    p_deploy.add_argument("--local", required=True)
    p_deploy.add_argument("--remote", required=True)
    p_deploy.add_argument("--execute", action="store_true")
    p_deploy.add_argument("--force", action="store_true",
                           help="Override drift protection. Use only after manually reviewing the server file.")
    p_deploy.add_argument("--json", action="store_true")
    p_deploy.set_defaults(func=cmd_deploy)

    p_batch = sub.add_parser("batch-deploy", help="Deploy a whole local folder to a remote folder.")
    p_batch.add_argument("--name", required=True)
    p_batch.add_argument("--local-dir", required=True)
    p_batch.add_argument("--remote-dir", required=True)
    p_batch.add_argument("--include", help="Comma-separated glob patterns to include, e.g. '*.php,*.css'")
    p_batch.add_argument("--exclude", help="Comma-separated glob patterns to exclude, e.g. 'node_modules/*,*.log'")
    p_batch.add_argument("--execute", action="store_true")
    p_batch.add_argument("--force", action="store_true")
    p_batch.add_argument("--json", action="store_true")
    p_batch.set_defaults(func=cmd_batch_deploy)

    p_download = sub.add_parser("download", help="Download a single remote file (dry-run unless --execute).")
    p_download.add_argument("--name", required=True)
    p_download.add_argument("--remote", required=True)
    p_download.add_argument("--local", required=True)
    p_download.add_argument("--execute", action="store_true")
    p_download.add_argument("--force", action="store_true")
    p_download.add_argument("--json", action="store_true")
    p_download.set_defaults(func=cmd_download)

    p_bdownload = sub.add_parser("batch-download", help="Download a whole remote folder to a local folder.")
    p_bdownload.add_argument("--name", required=True)
    p_bdownload.add_argument("--remote-dir", required=True)
    p_bdownload.add_argument("--local-dir", required=True)
    p_bdownload.add_argument("--include", help="Comma-separated glob patterns to include")
    p_bdownload.add_argument("--exclude", help="Comma-separated glob patterns to exclude")
    p_bdownload.add_argument("--execute", action="store_true")
    p_bdownload.add_argument("--force", action="store_true")
    p_bdownload.add_argument("--json", action="store_true")
    p_bdownload.set_defaults(func=cmd_batch_download)

    p_status = sub.add_parser("status", help="Check drift status of a remote file without deploying.")
    p_status.add_argument("--name", required=True)
    p_status.add_argument("--remote", required=True)
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_list = sub.add_parser("list", help="List a remote directory's contents (read-only).")
    p_list.add_argument("--name", required=True)
    p_list.add_argument("--remote-dir", required=True)
    p_list.add_argument("--recursive", action="store_true",
                         help="Walk subdirectories too (files only, no size/date info).")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
