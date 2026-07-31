import safe_ftp
import safe_ftp_mcp


def test_build_mcp_server_registers_all_eight_tools():
    server = safe_ftp_mcp._build_mcp_server()
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    assert tool_names == {
        "deploy", "batch_deploy", "download", "batch_download",
        "status", "history", "list_remote", "setup_site",
    }


def test_mcp_subcommand_parses():
    parser = safe_ftp._build_parser()
    args = parser.parse_args(["mcp"])
    assert args.func == safe_ftp.cmd_mcp


def test_install_subcommand_parses_with_target():
    parser = safe_ftp._build_parser()
    args = parser.parse_args(["install", "claude"])
    assert args.func == safe_ftp.cmd_install
    assert args.target == "claude"


def test_install_subcommand_rejects_unknown_target():
    import pytest
    parser = safe_ftp._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["install", "not-a-real-agent"])
