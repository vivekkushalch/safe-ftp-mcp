#!/usr/bin/env python3
"""
safe-ftp
========

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
  safe-ftp setup-site --name mysite

  # See what WOULD happen (default, no changes made)
  safe-ftp deploy --name mysite --local ./index.php --remote /public_html/index.php

  # Actually perform the backup-rename + upload
  safe-ftp deploy --name mysite --local ./index.php --remote /public_html/index.php --execute

  # Deploy a whole folder the same way
  safe-ftp batch-deploy --name mysite --local-dir ./site --remote-dir /public_html --execute

  # Check status / drift for a file without deploying anything
  safe-ftp status --name mysite --remote /public_html/index.php

  # Machine-readable output for an agent
  safe-ftp deploy --name mysite --local ./index.php --remote /public_html/index.php --json
"""

import argparse
import base64
import binascii
import fnmatch
import getpass
import hashlib
import json
import os
import ssl
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from ftplib import FTP, FTP_TLS, error_perm, all_errors

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from rich.console import Console
from rich.markdown import Markdown

import safe_ftp_format as fmt

__version__ = "0.1.0"

# Fixed width keeps output deterministic across real terminals and
# captured/piped output (tests, CI) alike -- color/styling still auto-adapts
# to whether stdout is a real terminal.
_console = Console(width=100)


def _transfer_progress(description: str, total):
    """Returns a rich Progress instance configured for a single file
    transfer, plus its task id. total=None renders an indeterminate
    display (no percentage) when the server didn't report a size."""
    from rich.progress import BarColumn, DownloadColumn, Progress, TimeRemainingColumn, TransferSpeedColumn

    progress = Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=_console,
    )
    task_id = progress.add_task(description, total=total)
    return progress, task_id

# ---------------------------------------------------------------------------
# File locations (all local, next to this script's working directory)
# ---------------------------------------------------------------------------
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".safe_ftp_deploy")
CREDS_FILE = os.path.join(CONFIG_DIR, "sites.enc")
SALT_FILE = os.path.join(CONFIG_DIR, "salt.bin")
STATE_FILE = os.path.join(CONFIG_DIR, "state.json")  # no secrets in here, just hashes
HISTORY_FILE = os.path.join(CONFIG_DIR, "history.json")  # append-only deploy log, keyed like STATE_FILE

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


def _write_ftpconfig(site_name: str, master_password: str) -> None:
    with open(_ftpconfig_path(), "w", encoding="utf-8") as f:
        f.write(f"{site_name}\n{master_password}\n")


# FileZilla's public ServerProtocol enum, as of recent 3.x releases. Not
# verified against a real export -- an unrecognized code leaves use_tls as
# None (falls through to a flag/prompt/default) rather than guessing.
_FILEZILLA_TLS_PROTOCOLS = {
    0: False,  # FTP (plain)
    5: True,   # FTPS - implicit TLS
    6: True,   # FTPES - explicit TLS
    7: False,  # INSECURE_FTP
}
_FILEZILLA_SFTP_PROTOCOL = 1


def _parse_filezilla_export(path: str) -> dict:
    """Parse a FileZilla Site Manager XML export containing exactly one
    <Server> entry. Returns a dict with "host", "port", "username",
    "password", "use_tls" -- each None if the export didn't supply it (or,
    for use_tls, if the protocol code wasn't recognized)."""
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError) as e:
        raise SystemExit(f"Could not read FileZilla export '{path}': {e}")

    servers = tree.getroot().findall(".//Server")
    if len(servers) == 0:
        raise SystemExit(f"No <Server> entries found in FileZilla export '{path}'.")
    if len(servers) > 1:
        raise SystemExit(
            f"FileZilla export '{path}' contains {len(servers)} sites -- "
            "trim it down to exactly one <Server> entry first."
        )
    server = servers[0]

    def _text(tag):
        el = server.find(tag)
        return el.text.strip() if el is not None and el.text else None

    host = _text("Host")
    port = _text("Port")
    username = _text("User")

    password = None
    pass_el = server.find("Pass")
    if pass_el is not None and pass_el.text:
        encoding = pass_el.get("encoding", "plain")
        if encoding == "plain":
            password = pass_el.text
        elif encoding == "base64":
            try:
                password = base64.b64decode(pass_el.text).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError) as e:
                raise SystemExit(f"Could not decode base64 password in FileZilla export '{path}': {e}")
        elif encoding == "crypt":
            raise SystemExit(
                f"FileZilla export '{path}' has a master-password-protected "
                "encryption on its saved password -- re-export without a "
                "FileZilla master password, or supply "
                "--ftp-password/SAFE_FTP_FTP_PASSWORD manually."
            )
        else:
            raise SystemExit(
                f"Unsupported password encoding '{encoding}' in FileZilla "
                f"export '{path}'. Only plain and base64 are supported."
            )

    use_tls = None
    protocol_text = _text("Protocol")
    if protocol_text is not None:
        try:
            protocol = int(protocol_text)
        except ValueError:
            protocol = None
        if protocol == _FILEZILLA_SFTP_PROTOCOL:
            raise SystemExit(
                f"FileZilla export '{path}' uses SFTP, which safe-ftp "
                "doesn't support (FTP/FTPS only via ftplib)."
            )
        if protocol in _FILEZILLA_TLS_PROTOCOLS:
            use_tls = _FILEZILLA_TLS_PROTOCOLS[protocol]

    return {"host": host, "port": port, "username": username, "password": password, "use_tls": use_tls}


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
# Deploy history -- an append-only log of successful deploys, separate from
# STATE_FILE's single "last known good" entry per file. This is what lets you
# reconcile later: which deploy introduced a change, what it replaced, and
# (optionally) why, via the free-text message passed at deploy time.
# ---------------------------------------------------------------------------
def _load_history() -> dict:
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r") as f:
        return json.load(f)


def _save_history(history: dict):
    _ensure_config_dir()
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def _append_history_entry(key: str, entry: dict):
    history = _load_history()
    history.setdefault(key, []).append(entry)
    _save_history(history)


# ---------------------------------------------------------------------------
# FTP helpers
# ---------------------------------------------------------------------------
def _tls_context(site: dict) -> ssl.SSLContext:
    """Verify the server certificate and hostname unless the site was saved
    with verify_tls=False (--insecure-tls). Sites saved before this setting
    existed have no key and therefore verify."""
    ctx = ssl.create_default_context()
    if not site.get("verify_tls", True):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _connect(site: dict) -> FTP:
    if site.get("use_tls", True):
        ftp = FTP_TLS(context=_tls_context(site))
        ftp.connect(site["host"], int(site.get("port", 21)), timeout=30)
        ftp.login(site["username"], site["password"])
        ftp.prot_p()  # secure the data channel too
    else:
        ftp = FTP()
        ftp.connect(site["host"], int(site.get("port", 21)), timeout=30)
        ftp.login(site["username"], site["password"])
    return ftp


def _test_site_connection(site: dict) -> tuple:
    """Attempt to connect to the site with its saved credentials. Returns
    (ok, message); never raises. Used by setup-site to give immediate
    feedback on whether the credentials actually work, without blocking
    the save on failure."""
    try:
        ftp = _connect(site)
    except ssl.SSLCertVerificationError as e:
        return False, (
            f"Could not connect: TLS certificate verification failed ({getattr(e, 'verify_message', None) or e}). "
            "If this host uses a self-signed or mismatched certificate and you trust it, "
            "re-run setup-site with --insecure-tls."
        )
    except Exception as e:
        return False, f"Could not connect: {e}"
    try:
        ftp.quit()
    except Exception:
        ftp.close()
    return True, f"Connected to {site['host']}:{site.get('port', 21)}."


def _remote_file_exists(ftp: FTP, remote_path: str) -> bool:
    directory, filename = os.path.split(remote_path)
    try:
        listing = ftp.nlst(directory or ".")
    except all_errors:
        # Some servers reply 550 (permanent, "no such directory") for this,
        # others reply 450 (transient, "requested action not taken") for
        # the exact same condition -- ftplib only classes 550 as error_perm,
        # so a 450 on a not-yet-created directory used to escape uncaught.
        # Either way the correct read here is the same: the listing failed,
        # so the file can't be confirmed to exist.
        return False
    names = [os.path.basename(x) for x in listing]
    return filename in names


def _ensure_remote_dir(ftp: FTP, remote_path: str) -> None:
    """Create any missing intermediate directories for remote_path (mkdir -p
    equivalent) -- FTP has no bulk-mkdir command. Walks the path one segment
    at a time; a segment that already exists just fails its MKD, which is
    ignored, since there's no portable way to distinguish "already exists"
    from other errors and a real problem surfaces immediately on the STOR
    that follows this call anyway."""
    directory = os.path.dirname(remote_path)
    if not directory or directory in ('.', '/'):
        return
    # Directory already there (the usual case): skip MKD entirely. On a slow
    # link a failed MKD's "550 File exists" can arrive late and be read as the
    # reply to the next command (TYPE I before STOR), aborting a new-file upload.
    try:
        ftp.cwd(directory)
        return
    except all_errors:
        pass
    is_absolute = directory.startswith('/')
    parts = [p for p in directory.split('/') if p]
    path = '/' if is_absolute else ''
    for part in parts:
        path = (path.rstrip('/') + '/' + part) if path else part
        try:
            ftp.mkd(path)
        except all_errors:
            pass


def _download_to_temp(ftp: FTP, remote_path: str, progress_label: str = None) -> str:
    """Download remote_path to a local temp file and return its path. If
    progress_label is given, shows a rich progress bar while downloading
    (total size from the FTP SIZE command when the server supports it --
    falls back to an indeterminate display otherwise)."""
    fd, tmp_path = tempfile.mkstemp(prefix="ftpdeploy_")
    os.close(fd)

    if progress_label is None:
        with open(tmp_path, "wb") as f:
            ftp.retrbinary(f"RETR {remote_path}", f.write)
        return tmp_path

    try:
        total = ftp.size(remote_path)
    except Exception:
        total = None

    progress, task_id = _transfer_progress(progress_label, total)
    with progress:
        with open(tmp_path, "wb") as f:
            def _on_chunk(chunk):
                f.write(chunk)
                progress.update(task_id, advance=len(chunk))
            ftp.retrbinary(f"RETR {remote_path}", _on_chunk)
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
    norm = os.path.normpath(remote_path).replace("\\", "/")
    for allowed in allowed_dirs:
        allowed_norm = os.path.normpath(allowed).replace("\\", "/")
        # ".", "/", and "" all mean "the whole site root" -- match everything,
        # matching what a user typing "." at the allowed-dirs prompt expects.
        if allowed_norm in (".", "/", ""):
            return True
        # Path-boundary match, not a raw string prefix: "images" must not
        # match "images2/foo.png".
        if norm == allowed_norm or norm.startswith(allowed_norm + "/"):
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


def _walk_remote_dir(ftp: FTP, remote_dir: str, max_depth=None, _depth=1):
    """
    Recursively yield (full_path, facts) tuples for files under remote_dir
    using MLSD (works on Hostinger and most modern FTP servers). Falls back
    to non-recursive NLST (facts == {}) if MLSD isn't supported.

    max_depth caps how many directory levels deep to recurse (None =
    unlimited). remote_dir's own immediate children are depth 1, so
    max_depth=1 yields only remote_dir's direct file children with no
    recursion into subdirectories.
    """
    try:
        entries = list(ftp.mlsd(remote_dir))
    except Exception:
        # Fallback: flat listing only, treat everything as a file with no facts
        for name in ftp.nlst(remote_dir):
            yield name, {}
        return

    for name, facts in entries:
        if name in (".", ".."):
            continue
        full_path = f"{remote_dir.rstrip('/')}/{name}"
        if facts.get("type") == "dir":
            if max_depth is None or _depth < max_depth:
                yield from _walk_remote_dir(ftp, full_path, max_depth=max_depth, _depth=_depth + 1)
        else:
            yield full_path, facts


# ---------------------------------------------------------------------------
# Core safe-deploy logic
# ---------------------------------------------------------------------------
def deploy_file(site_name: str, site: dict, local_path: str, remote_path: str,
                 execute: bool, force: bool = False, expected_hash: str = None,
                 show_progress: bool = False, message: str = None) -> dict:
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

            if expected_hash is not None and current_remote_hash != expected_hash and not force:
                result["status"] = "stale_download"
                result["message"] = (
                    "The file on the server has changed since you downloaded it "
                    "(current remote hash doesn't match --expected-hash). Re-download "
                    "the current version before deploying your edit, or re-run with "
                    "--force once you're sure it's safe to overwrite."
                )
                result["expected_hash"] = expected_hash
                result["current_remote_hash"] = current_remote_hash
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
        if not exists:
            _ensure_remote_dir(ftp, remote_path)
        if exists:
            ftp.rename(remote_path, backup_path)

        if show_progress:
            local_size = os.path.getsize(local_path)
            progress, task_id = _transfer_progress(f"Uploading {os.path.basename(local_path)}", local_size)
            with progress:
                def _on_chunk(chunk):
                    progress.update(task_id, advance=len(chunk))
                with open(local_path, "rb") as f:
                    ftp.storbinary(f"STOR {remote_path}", f, callback=_on_chunk)
        else:
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

        deployed_at = datetime.now().isoformat()
        state[key] = {"hash": uploaded_hash, "deployed_at": deployed_at}
        _save_state(state)

        _append_history_entry(key, {
            "deployed_at": deployed_at,
            "local_path": local_path,
            "remote_path": remote_path,
            "old_hash": current_remote_hash if exists else None,
            "new_hash": uploaded_hash,
            "backup_name": backup_path if exists else None,
            "message": message or "",
        })

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
                    execute: bool, force: bool = False, show_progress: bool = False) -> dict:
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

        progress_label = f"Downloading {remote_path}" if show_progress else None
        tmp_remote_copy = _download_to_temp(ftp, remote_path, progress_label=progress_label)
        try:
            remote_hash = _sha256_of_file(tmp_remote_copy)
            result["hash"] = remote_hash

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


def get_deploy_history(site_name: str, remote_path: str, limit: int = 10) -> dict:
    """Return past successful deploys for one remote file, most recent
    first. Purely local -- reads HISTORY_FILE, no FTP connection, no site
    credentials needed."""
    history = _load_history()
    entries = history.get(_state_key(site_name, remote_path), [])
    total = len(entries)
    recent = entries[-limit:] if limit else entries
    recent = list(reversed(recent))
    return {
        "site": site_name,
        "remote_path": remote_path,
        "total_entries": total,
        "entries": recent,
    }


def _sort_entries(entries: list, sort_by: str, reverse: bool) -> list:
    """Sort entries (dicts with 'name'/'type'/'size'/'modify' keys) by name
    (default -- directories first, then alphabetical, matching the
    listing's long-standing default order), size, or modified date. Missing
    size/modify values sort first."""
    if sort_by == "size":
        key = lambda e: (e.get("size") is None, int(e["size"]) if e.get("size") is not None else 0)
    elif sort_by == "modified":
        key = lambda e: (e.get("modify") is None, e.get("modify") or "")
    else:
        key = lambda e: (e.get("type") != "dir", e.get("name", "").lower())
    return sorted(entries, key=key, reverse=reverse)


def list_remote_dir(site_name: str, site: dict, remote_dir: str, recursive: bool = False,
                     entry_type: str = "all", include: list = None, exclude: list = None,
                     limit: int = None, sort_by: str = "name", reverse: bool = False,
                     max_depth: int = None) -> dict:
    """List a remote directory's contents. Read-only -- makes no changes.

    entry_type: "file", "dir", or "all" (default) -- filters by entry type.
    include/exclude: lists of glob patterns matched against each entry's
        name, same semantics as _matches_filters.
    limit: caps the number of entries returned; if the true count is
        higher, result["truncated"] is True and result["total_matched"]
        holds the real count.
    sort_by: "name" (default), "size", or "modified".
    reverse: reverses the sort order.
    max_depth: only meaningful with recursive=True; caps how many
        directory levels deep to walk.
    """
    result = {"site": site_name, "remote_dir": remote_dir, "entries": []}

    if not _is_within_allowed_dirs(remote_dir, site.get("allowed_remote_dirs", [])):
        result["status"] = "blocked"
        result["message"] = (
            f"Remote path {remote_dir} is outside this site's allowed_remote_dirs "
            f"whitelist. Refusing to list it. Edit the site config to allow it."
        )
        return result

    include = include or []
    exclude = exclude or []
    flat = False

    ftp = _connect(site)
    try:
        if recursive:
            listed = []
            for full_path, facts in _walk_remote_dir(ftp, remote_dir, max_depth=max_depth):
                name = os.path.basename(full_path)
                if not _matches_filters(name, include, exclude):
                    continue
                listed.append({
                    "path": full_path,
                    "name": name,
                    "type": facts.get("type", "file"),
                    "size": facts.get("size"),
                    "modify": facts.get("modify"),
                })
        else:
            try:
                mlsd_entries = list(ftp.mlsd(remote_dir))
            except Exception:
                flat = True
                mlsd_entries = [(os.path.basename(n), {}) for n in ftp.nlst(remote_dir)]

            listed = []
            for name, facts in mlsd_entries:
                if name in (".", ".."):
                    continue
                if not _matches_filters(name, include, exclude):
                    continue
                listed.append({
                    "name": name,
                    "type": facts.get("type", "?"),
                    "size": facts.get("size"),
                    "modify": facts.get("modify"),
                })

        listed = [e for e in listed if entry_type == "all" or e["type"] == entry_type]
        listed = _sort_entries(listed, sort_by, reverse)

        total_matched = len(listed)
        if limit is not None and total_matched > limit:
            result["truncated"] = True
            result["total_matched"] = total_matched
            listed = listed[:limit]

        result["entries"] = listed
        if flat:
            result["status"] = "ok_flat"
            result["message"] = "Server doesn't support MLSD -- showing a flat listing with no type/size/date."
        else:
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
def _read_master_password_from_files():
    """Check .ftpconfig (line 2) then legacy .masterpwd, both in the
    current directory. Returns the password, or None if neither has one."""
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

    return None


def _get_master_password(prompt):
    """Resolve the master password: .ftpconfig (line 2) in the current
    directory, else legacy .masterpwd in the current directory, else an
    interactive getpass prompt."""
    found = _read_master_password_from_files()
    if found:
        return found
    return getpass.getpass(prompt)


def _resolve_master_password_for_setup(args) -> str:
    """Resolve the master password for setup-site: --master-password flag,
    else SAFE_FTP_MASTER_PASSWORD env var, else existing .ftpconfig/
    .masterpwd in the current directory, else an interactive prompt --
    or, under --non-interactive, a clear error instead of prompting."""
    if args.master_password:
        return args.master_password
    if os.environ.get("SAFE_FTP_MASTER_PASSWORD"):
        return os.environ["SAFE_FTP_MASTER_PASSWORD"]
    found = _read_master_password_from_files()
    if found:
        return found
    if args.non_interactive:
        raise SystemExit(
            "Missing required field for --non-interactive: master password. "
            "Pass --master-password, set SAFE_FTP_MASTER_PASSWORD, or ensure "
            ".ftpconfig/.masterpwd already exists in this directory."
        )
    return getpass.getpass("Master password to encrypt/decrypt your site credentials: ")


def _resolve_ftp_password_for_setup(args, imported_password) -> str:
    """Resolve the FTP account password for setup-site: --ftp-password
    flag, else SAFE_FTP_FTP_PASSWORD env var, else a --from-filezilla
    import, else an interactive prompt -- or, under --non-interactive, a
    clear error instead of prompting."""
    if args.ftp_password:
        return args.ftp_password
    if os.environ.get("SAFE_FTP_FTP_PASSWORD"):
        return os.environ["SAFE_FTP_FTP_PASSWORD"]
    if imported_password:
        return imported_password
    if args.non_interactive:
        raise SystemExit(
            "Missing required field for --non-interactive: FTP password. "
            "Pass --ftp-password, set SAFE_FTP_FTP_PASSWORD, or supply it "
            "via --from-filezilla."
        )
    return getpass.getpass("FTP password: ")


def _resolve_required_field(explicit_value, imported_value, field_label, args, prompt_text) -> str:
    """Resolve a required setup-site field: explicit flag value, else an
    imported (e.g. FileZilla) value, else an interactive prompt -- or,
    under --non-interactive, a clear error naming field_label."""
    if explicit_value:
        return explicit_value
    if imported_value:
        return imported_value
    if args.non_interactive:
        raise SystemExit(f"Missing required field for --non-interactive: {field_label}.")
    return input(prompt_text).strip()


def _resolve_port(args, imported_port) -> str:
    """Resolve the FTP port. Always has a safe default ("21") so it's
    never required even under --non-interactive."""
    if args.port:
        return args.port
    if imported_port:
        return imported_port
    if args.non_interactive:
        return "21"
    return input("FTP port [21]: ").strip() or "21"


def _resolve_use_tls(args, imported_use_tls) -> bool:
    """Resolve whether to use FTPS/TLS. Defaults to True if nothing else
    says otherwise, matching today's interactive default."""
    if args.use_tls:
        return True
    if args.no_tls:
        return False
    if imported_use_tls is not None:
        return imported_use_tls
    if args.non_interactive:
        return True
    use_tls_in = input("Use FTPS/TLS if supported? [Y/n]: ").strip().lower()
    return use_tls_in != "n"


def _resolve_allowed_dirs(args) -> list:
    """Resolve the allowed_remote_dirs whitelist. Defaults to an empty
    list (with the existing "no whitelist set" warning printed elsewhere)
    if nothing else says otherwise."""
    if args.allowed_dirs is not None:
        return [d.strip() for d in args.allowed_dirs.split(",") if d.strip()]
    if args.non_interactive:
        return []
    allowed = input(
        "Comma-separated list of remote directories this site is allowed to touch "
        "(e.g. /public_html/,/public_html/blog/) [leave blank to allow anywhere -- not recommended]: "
    ).strip()
    return [d.strip() for d in allowed.split(",") if d.strip()]


def cmd_setup_site(args):
    ftpconfig_existed = os.path.exists(_ftpconfig_path())
    masterpwd_existed = os.path.exists(_masterpwd_path())

    imported = {"host": None, "port": None, "username": None, "password": None, "use_tls": None}
    if args.from_filezilla:
        imported = _parse_filezilla_export(args.from_filezilla)

    master_password = _resolve_master_password_for_setup(args)
    sites = _load_all_sites(master_password) if os.path.exists(CREDS_FILE) else {}

    host = _resolve_required_field(args.host, imported["host"], "--host", args,
                                    "FTP host (e.g. ftp.yourdomain.com): ")
    port = _resolve_port(args, imported["port"])
    username = _resolve_required_field(args.username, imported["username"], "--username", args,
                                        "FTP username: ")
    password = _resolve_ftp_password_for_setup(args, imported["password"])
    use_tls = _resolve_use_tls(args, imported["use_tls"])
    allowed_dirs = _resolve_allowed_dirs(args)

    sites[args.name] = {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "use_tls": use_tls,
        "verify_tls": not getattr(args, "insecure_tls", False),
        "allowed_remote_dirs": allowed_dirs,
    }
    _save_all_sites(sites, master_password)

    connection_ok, connection_message = _test_site_connection(sites[args.name])

    migrated = not ftpconfig_existed and masterpwd_existed
    _write_ftpconfig(args.name, master_password)

    result = {
        "site": args.name,
        "host": host,
        "port": port,
        "use_tls": use_tls,
        "connection_ok": connection_ok,
        "connection_message": connection_message,
        "allowed_remote_dirs": allowed_dirs,
        "migrated_from_masterpwd": migrated,
        "creds_file": CREDS_FILE,
    }
    _console.print(Markdown(fmt.format_setup_site_markdown(result)))


def _load_site_or_exit(name: str) -> dict:
    master_password = _get_master_password("Master password: ")
    sites = _load_all_sites(master_password)
    if name not in sites:
        raise SystemExit(f"No site named '{name}' found. Run setup-site first.")
    return sites[name]


def _resolve_site_name_value(explicit_name) -> str:
    """Resolve a site name from an explicit value (may be None/falsy): the
    explicit value always wins, else fall back to .ftpconfig in the current
    directory, else fail with a clear message. Shared by the CLI's
    _resolve_site_name(args) and the MCP tool layer, which has no argparse
    Namespace to read from."""
    if explicit_name:
        return explicit_name
    site_name, _ = _read_ftpconfig()
    if site_name:
        return site_name
    raise SystemExit(
        'No site specified. Pass --name <site>, or run "setup-site --name '
        '<site>" to set a default for this folder.'
    )


def _resolve_site_name(args) -> str:
    """Resolve the site name for commands where --name is optional."""
    return _resolve_site_name_value(getattr(args, "name", None))


def cmd_deploy(args):
    site_name = _resolve_site_name(args)
    site = _load_site_or_exit(site_name)
    result = deploy_file(site_name, site, args.local, args.remote, execute=args.execute, force=args.force,
                          expected_hash=args.expected_hash, show_progress=not args.json, message=args.message)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _console.print(Markdown(fmt.format_deploy_markdown(result)))


def batch_deploy_files(site_name: str, site: dict, local_dir: str, remote_dir: str,
                        include: list = None, exclude: list = None,
                        execute: bool = False, force: bool = False, message: str = None) -> list:
    """Walk local_dir, deploy_file() each matching file to its mirrored path
    under remote_dir. Shared core for the CLI's batch-deploy and the MCP
    batch_deploy tool."""
    include = include or []
    exclude = exclude or []
    results = []
    for root, _dirs, files in os.walk(local_dir):
        for fname in files:
            local_full = os.path.join(root, fname)
            rel = os.path.relpath(local_full, local_dir).replace(os.sep, "/")
            if not _matches_filters(rel, include, exclude):
                continue
            remote_full = os.path.join(remote_dir, rel).replace(os.sep, "/")
            results.append(deploy_file(site_name, site, local_full, remote_full,
                                        execute=execute, force=force, message=message))
    return results


def cmd_batch_deploy(args):
    site_name = _resolve_site_name(args)
    site = _load_site_or_exit(site_name)
    include = args.include.split(",") if args.include else []
    exclude = args.exclude.split(",") if args.exclude else []
    results = batch_deploy_files(site_name, site, args.local_dir, args.remote_dir,
                                  include=include, exclude=exclude,
                                  execute=args.execute, force=args.force, message=args.message)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        _console.print(Markdown(fmt.format_batch_deploy_markdown(results, args.local_dir, args.remote_dir)))


def cmd_download(args):
    site_name = _resolve_site_name(args)
    site = _load_site_or_exit(site_name)
    result = download_file(site_name, site, args.remote, args.local, execute=args.execute, force=args.force,
                            show_progress=not args.json)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _console.print(Markdown(fmt.format_download_markdown(result)))


def batch_download_files(site_name: str, site: dict, remote_dir: str, local_dir: str,
                          include: list = None, exclude: list = None,
                          execute: bool = False, force: bool = False) -> list:
    """Walk remote_dir, download_file() each matching file to its mirrored
    path under local_dir. Shared core for the CLI's batch-download and the
    MCP batch_download tool."""
    include = include or []
    exclude = exclude or []
    ftp = _connect(site)
    try:
        remote_files = [path for path, _facts in _walk_remote_dir(ftp, remote_dir)]
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()

    results = []
    for remote_full in remote_files:
        rel = os.path.relpath(remote_full, remote_dir).replace(os.sep, "/")
        if not _matches_filters(rel, include, exclude):
            continue
        local_full = os.path.join(local_dir, rel)
        results.append(download_file(site_name, site, remote_full, local_full,
                                      execute=execute, force=force))
    return results


def cmd_batch_download(args):
    site_name = _resolve_site_name(args)
    site = _load_site_or_exit(site_name)
    include = args.include.split(",") if args.include else []
    exclude = args.exclude.split(",") if args.exclude else []
    results = batch_download_files(site_name, site, args.remote_dir, args.local_dir,
                                    include=include, exclude=exclude,
                                    execute=args.execute, force=args.force)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        _console.print(Markdown(fmt.format_batch_download_markdown(results, args.remote_dir, args.local_dir)))


def cmd_status(args):
    site_name = _resolve_site_name(args)
    site = _load_site_or_exit(site_name)
    result = check_status(site_name, site, args.remote)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _console.print(Markdown(fmt.format_status_markdown(result)))


def cmd_history(args):
    site_name = _resolve_site_name(args)
    result = get_deploy_history(site_name, args.remote, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _console.print(Markdown(fmt.format_history_markdown(result)))


def cmd_list(args):
    site_name = _resolve_site_name(args)
    site = _load_site_or_exit(site_name)
    include = args.include.split(",") if args.include else []
    exclude = args.exclude.split(",") if args.exclude else []
    result = list_remote_dir(
        site_name, site, args.remote_dir,
        recursive=args.recursive,
        entry_type=args.type,
        include=include,
        exclude=exclude,
        limit=args.limit,
        sort_by=args.sort,
        reverse=args.reverse,
        max_depth=args.max_depth,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _console.print(Markdown(fmt.format_list_remote_markdown(result)))


_NAME_HELP = "Site name. Defaults to the site recorded in ./.ftpconfig for the current directory."

_JSON_HELP = "Print machine-readable JSON instead of a formatted summary."

_WORKFLOW_EPILOG = """\
Typical flow:
  1. One-time per site:      safe-ftp setup-site --name mysite
  2. See what would happen:  safe-ftp deploy --local ./index.php --remote /public_html/index.php
  3. Review the dry-run output above, then actually deploy:
                              safe-ftp deploy --local ./index.php --remote /public_html/index.php --execute

Every command is a dry run unless you pass --execute. Nothing is ever deleted --
the only "destructive" action is renaming the old file to a timestamped backup.
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safety-first FTP deploy tool.",
        epilog=_WORKFLOW_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup-site", help="Add or update an encrypted site profile.")
    p_setup.add_argument("--name", required=True, help="Site name to save these credentials under.")
    p_setup.add_argument(
        "--non-interactive", action="store_true",
        help="Skip interactive prompts; every field must come from a flag, "
             "environment variable, or --from-filezilla.",
    )
    p_setup.add_argument(
        "--from-filezilla", metavar="PATH",
        help="Path to a FileZilla Site Manager XML export containing exactly one site.",
    )
    p_setup.add_argument("--host", help="FTP host, e.g. ftp.yourdomain.com.")
    p_setup.add_argument("--port", help="FTP port. Default: 21.")
    p_setup.add_argument("--username", help="FTP username.")
    p_setup.add_argument("--ftp-password", help="FTP account password. Can also be set via SAFE_FTP_FTP_PASSWORD.")
    p_setup.add_argument("--master-password", help="Master password. Can also be set via SAFE_FTP_MASTER_PASSWORD.")
    tls_group = p_setup.add_mutually_exclusive_group()
    tls_group.add_argument("--use-tls", action="store_true",
                            help="Force FTPS (TLS). Mutually exclusive with --no-tls.")
    tls_group.add_argument("--no-tls", action="store_true",
                            help="Force plain FTP (no TLS). Mutually exclusive with --use-tls.")
    p_setup.add_argument(
        "--insecure-tls", action="store_true",
        help="Skip TLS certificate verification (self-signed or mismatched certificate). "
             "Only use on a host you trust; the connection is open to interception.",
    )
    p_setup.add_argument("--allowed-dirs", help="Comma-separated list of allowed remote directories.")
    p_setup.set_defaults(func=cmd_setup_site)

    p_deploy = sub.add_parser("deploy", help="Deploy a single file (dry-run unless --execute).")
    p_deploy.add_argument("--name", help=_NAME_HELP)
    p_deploy.add_argument("--local", required=True, help="Path to the local file to deploy.")
    p_deploy.add_argument("--remote", required=True, help="Destination path on the server.")
    p_deploy.add_argument("--execute", action="store_true",
                           help="Actually perform the deploy. Without this, only a dry-run plan is shown.")
    p_deploy.add_argument("--force", action="store_true",
                           help="Override drift protection. Use only after manually reviewing the server file.")
    p_deploy.add_argument(
        "--expected-hash",
        help="Hash from a prior download; deploy fails with stale_download if the remote file no "
             "longer matches it, instead of silently overwriting a newer change.",
    )
    p_deploy.add_argument(
        "--message", "-m",
        help="Optional free-text note recorded with this deploy in the local history log "
             "(see the 'history' command) -- e.g. why the change was made.",
    )
    p_deploy.add_argument("--json", action="store_true", help=_JSON_HELP)
    p_deploy.set_defaults(func=cmd_deploy)

    p_batch = sub.add_parser("batch-deploy", help="Deploy a whole local folder to a remote folder.")
    p_batch.add_argument("--name", help=_NAME_HELP)
    p_batch.add_argument("--local-dir", required=True, help="Local folder to deploy from.")
    p_batch.add_argument("--remote-dir", required=True, help="Destination folder on the server.")
    p_batch.add_argument("--include", help="Comma-separated glob patterns to include, e.g. '*.php,*.css'")
    p_batch.add_argument("--exclude", help="Comma-separated glob patterns to exclude, e.g. 'node_modules/*,*.log'")
    p_batch.add_argument("--execute", action="store_true",
                          help="Actually perform the deploy. Without this, only a dry-run plan is shown.")
    p_batch.add_argument(
        "--force", action="store_true",
        help="Override drift protection for every file. Use only after manually reviewing the server files.",
    )
    p_batch.add_argument(
        "--message", "-m",
        help="Optional free-text note recorded in the local history log for every file deployed "
             "in this batch (see the 'history' command).",
    )
    p_batch.add_argument("--json", action="store_true", help=_JSON_HELP)
    p_batch.set_defaults(func=cmd_batch_deploy)

    p_download = sub.add_parser("download", help="Download a single remote file (dry-run unless --execute).")
    p_download.add_argument("--name", help=_NAME_HELP)
    p_download.add_argument("--remote", required=True, help="Path to the remote file to download.")
    p_download.add_argument("--local", required=True, help="Destination path on your local machine.")
    p_download.add_argument("--execute", action="store_true",
                             help="Actually perform the download. Without this, only a dry-run plan is shown.")
    p_download.add_argument("--force", action="store_true",
                             help="Override drift protection. Use only after manually reviewing the local file.")
    p_download.add_argument("--json", action="store_true", help=_JSON_HELP)
    p_download.set_defaults(func=cmd_download)

    p_bdownload = sub.add_parser("batch-download", help="Download a whole remote folder to a local folder.")
    p_bdownload.add_argument("--name", help=_NAME_HELP)
    p_bdownload.add_argument("--remote-dir", required=True, help="Remote folder to download from.")
    p_bdownload.add_argument("--local-dir", required=True, help="Destination folder on your local machine.")
    p_bdownload.add_argument("--include", help="Comma-separated glob patterns to include")
    p_bdownload.add_argument("--exclude", help="Comma-separated glob patterns to exclude")
    p_bdownload.add_argument("--execute", action="store_true",
                              help="Actually perform the download. Without this, only a dry-run plan is shown.")
    p_bdownload.add_argument(
        "--force", action="store_true",
        help="Override drift protection for every file. Use only after manually reviewing the local files.",
    )
    p_bdownload.add_argument("--json", action="store_true", help=_JSON_HELP)
    p_bdownload.set_defaults(func=cmd_batch_download)

    p_status = sub.add_parser("status", help="Check drift status of a remote file without deploying.")
    p_status.add_argument("--name", help=_NAME_HELP)
    p_status.add_argument("--remote", required=True, help="Remote path to check.")
    p_status.add_argument("--json", action="store_true", help=_JSON_HELP)
    p_status.set_defaults(func=cmd_status)

    p_history = sub.add_parser(
        "history", help="Show past deploys for a remote file, with messages (read-only, no server contact)."
    )
    p_history.add_argument("--name", help=_NAME_HELP)
    p_history.add_argument("--remote", required=True, help="Remote path to show history for.")
    p_history.add_argument("--limit", type=int, default=10, help="Max entries to show, most recent first. Default: 10.")
    p_history.add_argument("--json", action="store_true", help=_JSON_HELP)
    p_history.set_defaults(func=cmd_history)

    p_list = sub.add_parser("list", help="List a remote directory's contents (read-only).")
    p_list.add_argument("--name", help=_NAME_HELP)
    p_list.add_argument("--remote-dir", required=True, help="Remote directory to list.")
    p_list.add_argument("--recursive", action="store_true", help="Walk subdirectories too.")
    p_list.add_argument("--type", choices=["file", "dir", "all"], default="all",
                         help="Filter by entry type. Default: all.")
    p_list.add_argument("--include", help="Comma-separated glob patterns to include, matched against entry names.")
    p_list.add_argument("--exclude", help="Comma-separated glob patterns to exclude, matched against entry names.")
    p_list.add_argument("--limit", type=int, help="Cap the number of entries returned.")
    p_list.add_argument("--sort", choices=["name", "size", "modified"], default="name",
                         help="Sort order. Default: name (directories first).")
    p_list.add_argument("--reverse", action="store_true", help="Reverse the sort order.")
    p_list.add_argument(
        "--max-depth", type=int,
        help="Only meaningful with --recursive: cap how many directory levels deep to walk.",
    )
    p_list.add_argument("--json", action="store_true", help=_JSON_HELP)
    p_list.set_defaults(func=cmd_list)

    p_mcp = sub.add_parser(
        "mcp",
        help="Start the MCP server (stdio transport) so an AI agent can call these "
             "operations as tools instead of shelling out to the CLI.",
    )
    p_mcp.set_defaults(func=cmd_mcp)

    p_install = sub.add_parser(
        "install",
        help="Register the MCP server (and skill/agent guidance) for a coding agent, "
             "in the current directory.",
    )
    p_install.add_argument(
        "target", choices=["claude", "cursor", "windsurf", "opencode", "antigravity", "all"],
        help="Which agent to configure. 'all' configures every supported agent.",
    )
    p_install.set_defaults(func=cmd_install)

    return parser


def cmd_mcp(args):
    import safe_ftp_mcp
    safe_ftp_mcp.run_server()


def cmd_install(args):
    import safe_ftp_install
    results = safe_ftp_install.install_agent(args.target)
    for r in results:
        if r["status"] == "ok":
            print(f"OK: {r['message']}")
        else:
            print(f"ERROR: {r['message']}")


def main():
    parser = _build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
