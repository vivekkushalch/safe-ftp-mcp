# Changelog

All notable changes are documented here. Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- TLS certificate and hostname verification for FTPS, on by default; `setup-site --insecure-tls` opts out for trusted self-signed hosts.
- Agent skill and `AGENTS.md` guidance now cover TLS, password handling, the expected-hash edit workflow and result statuses.
- Project logo, `SECURITY.md`, `CONTRIBUTING.md`, GitHub Actions CI.

### Changed
- README restructured.

## [0.1.0]

Initial version: encrypted site profiles, dry-run-by-default deploy/download, drift detection, directory whitelist, post-upload verification, deploy history, MCP server, agent skill, multi-agent `install` command.
