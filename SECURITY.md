# Security Policy

Safe FTP Deploy stores FTP credentials and is meant to be driven by AI agents, so security reports are taken seriously.

## Supported versions

Only the latest release on `main` receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Use GitHub's private reporting: **Security → Report a vulnerability** on the [repository page](https://github.com/vivekkushalch/safe-ftp-mcp/security/advisories/new).

Include what you found, steps to reproduce, and the impact. You can expect an acknowledgement within a few days and a fix or mitigation plan after triage.

## What counts

In scope, for example:

- Any path that deletes or overwrites remote data without a backup rename
- Bypassing the directory whitelist, drift detection, or the dry-run default
- Credential disclosure (logs, MCP output, error messages, files on disk)
- Weaknesses in the credential encryption or TLS handling

Out of scope: issues that need an attacker who already controls your machine or your FTP server, and the documented plain-text `.ftpconfig` trade-off.

## Hardening notes

- TLS certificates are verified by default. `--insecure-tls` disables that and should only be used on hosts you trust.
- Prefer `SAFE_FTP_FTP_PASSWORD` / `SAFE_FTP_MASTER_PASSWORD` over command-line flags.
- Keep `.ftpconfig` out of backups and version control.
