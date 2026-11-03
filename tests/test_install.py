import json

import pytest

import safe_ftp_install as install


# --- _merge_top_level_entry ---

def test_merge_creates_file_and_key_when_missing(tmp_path):
    path = str(tmp_path / "config.json")
    action = install._merge_top_level_entry(path, "mcpServers", "safe-ftp", {"command": "x"})

    assert action == "created"
    data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert data == {"mcpServers": {"safe-ftp": {"command": "x"}}}


def test_merge_preserves_other_existing_entries(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mcpServers": {"other-server": {"command": "y"}}}), encoding="utf-8")

    install._merge_top_level_entry(str(path), "mcpServers", "safe-ftp", {"command": "x"})

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other-server"] == {"command": "y"}
    assert data["mcpServers"]["safe-ftp"] == {"command": "x"}


def test_merge_reports_unchanged_when_entry_already_matches(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mcpServers": {"safe-ftp": {"command": "x"}}}), encoding="utf-8")

    action = install._merge_top_level_entry(str(path), "mcpServers", "safe-ftp", {"command": "x"})

    assert action == "unchanged"


def test_merge_reports_updated_when_entry_differs(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mcpServers": {"safe-ftp": {"command": "old"}}}), encoding="utf-8")

    action = install._merge_top_level_entry(str(path), "mcpServers", "safe-ftp", {"command": "new"})

    assert action == "updated"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["safe-ftp"] == {"command": "new"}


def test_merge_refuses_invalid_json_without_overwriting(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not valid json", encoding="utf-8")

    with pytest.raises(ValueError):
        install._merge_top_level_entry(str(path), "mcpServers", "safe-ftp", {"command": "x"})

    # File must be untouched.
    assert path.read_text(encoding="utf-8") == "{ not valid json"


# --- install_claude (mcpServers shape, project-level, "type": "stdio") ---

def test_install_claude_writes_mcp_json(tmp_path):
    result = install.install_claude(cwd=str(tmp_path))

    assert result["status"] == "ok"
    data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["safe-ftp"] == {
        "type": "stdio", "command": "safe-ftp", "args": ["mcp"],
    }


def test_install_claude_skill_writes_skill_md(tmp_path):
    result = install.install_claude_skill(cwd=str(tmp_path))

    assert result["status"] == "ok"
    skill_path = tmp_path / ".claude" / "skills" / "safe-ftp" / "SKILL.md"
    assert skill_path.exists()
    content = skill_path.read_text(encoding="utf-8")
    assert content.startswith("---\nname: safe-ftp")
    assert "Dry run first, always" in content


# --- install_opencode (divergent shape: "mcp" key, combined command array) ---

def test_install_opencode_writes_opencode_json(tmp_path):
    result = install.install_opencode(cwd=str(tmp_path))

    assert result["status"] == "ok"
    data = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert data["mcp"]["safe-ftp"] == {
        "type": "local", "command": ["safe-ftp", "mcp"], "enabled": True,
    }


# --- Smoke tests: cursor/windsurf/antigravity (structurally like claude, no "type") ---

def test_install_cursor_writes_correct_path_and_entry(tmp_path):
    result = install.install_cursor(cwd=str(tmp_path))

    assert result["status"] == "ok"
    data = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["safe-ftp"] == {"command": "safe-ftp", "args": ["mcp"]}


def test_install_windsurf_writes_correct_path_and_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(install.os.path, "expanduser", lambda p: str(tmp_path))

    result = install.install_windsurf()

    assert result["status"] == "ok"
    data = json.loads((tmp_path / ".codeium" / "windsurf" / "mcp_config.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["safe-ftp"] == {"command": "safe-ftp", "args": ["mcp"]}


def test_install_antigravity_writes_correct_path_and_entry(tmp_path):
    result = install.install_antigravity(cwd=str(tmp_path))

    assert result["status"] == "ok"
    data = json.loads((tmp_path / ".agents" / "mcp_config.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["safe-ftp"] == {"command": "safe-ftp", "args": ["mcp"]}


# --- install_agents_md ---

def test_install_agents_md_creates_new_file(tmp_path):
    result = install.install_agents_md(cwd=str(tmp_path))

    assert result["status"] == "ok"
    content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "BEGIN safe-ftp agent guidance" in content
    assert "execute=False" in content


def test_install_agents_md_appends_to_existing_content(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# My project\n\nSome existing notes.\n", encoding="utf-8")

    install.install_agents_md(cwd=str(tmp_path))

    content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "Some existing notes." in content
    assert "BEGIN safe-ftp agent guidance" in content


def test_install_agents_md_updates_existing_block_in_place_without_duplicating(tmp_path):
    install.install_agents_md(cwd=str(tmp_path))
    install.install_agents_md(cwd=str(tmp_path))

    content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert content.count("BEGIN safe-ftp agent guidance") == 1


# --- install_agent dispatcher ---

def test_install_agent_claude_returns_two_results(tmp_path):
    results = install.install_agent("claude", cwd=str(tmp_path))

    assert len(results) == 2
    assert all(r["status"] == "ok" for r in results)


def test_install_agent_all_runs_every_target(tmp_path):
    results = install.install_agent("all", cwd=str(tmp_path))

    # claude(2) + cursor(2) + windsurf(2) + opencode(2) + antigravity(2)
    assert len(results) == 10
    assert all(r["status"] == "ok" for r in results)


def test_install_agent_unknown_target_raises_system_exit(tmp_path):
    with pytest.raises(SystemExit):
        install.install_agent("not-a-real-agent", cwd=str(tmp_path))


def test_embedded_skill_matches_skill_file():
    import pathlib

    skill_file = pathlib.Path(__file__).parent.parent / "skill" / "safe-ftp" / "SKILL.md"
    on_disk = skill_file.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert on_disk == install.SKILL_MD_CONTENT
