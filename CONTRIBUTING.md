# Contributing

Thanks for helping out. Issues and pull requests are welcome.

## Ground rules

Safe FTP Deploy has two promises. Every change must keep them:

1. **No delete path.** The tool never removes remote or local files; replacing a file means renaming it to a timestamped backup.
2. **No write without `--execute`.** Dry-run is the default in the CLI and in every MCP tool.

PRs that weaken either will not be merged.

## Development setup

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.10+.

```bash
git clone https://github.com/vivekkushalch/safe-ftp-mcp.git
cd safe-ftp-mcp
uv sync
uv run pytest
uv run safe-ftp-deploy --help
```

## Making a change

1. Create a branch: `git checkout -b feature/my-change`
2. Add or update tests in `tests/` (no real FTP server is needed; see existing tests for the fakes)
3. Run `uv run pytest` and make sure it passes
4. Keep code compatible with Python 3.10 (for example, no nested same-type quotes inside f-strings)
5. Open a pull request describing what changed and why

## Reporting bugs

Open an issue with the command you ran (passwords removed), what you expected, and what happened. For security problems, follow [SECURITY.md](SECURITY.md) instead.
