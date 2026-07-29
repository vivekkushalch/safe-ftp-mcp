import pytest

import safe_ftp


@pytest.mark.parametrize(
    "argv",
    [
        ["deploy", "--local", "a", "--remote", "b"],
        ["batch-deploy", "--local-dir", "a", "--remote-dir", "b"],
        ["download", "--remote", "a", "--local", "b"],
        ["batch-download", "--remote-dir", "a", "--local-dir", "b"],
        ["status", "--remote", "a"],
        ["list", "--remote-dir", "a"],
    ],
)
def test_name_is_optional_on_site_commands(argv):
    parser = safe_ftp._build_parser()
    args = parser.parse_args(argv)
    assert args.name is None


def test_name_is_still_required_on_setup_site():
    parser = safe_ftp._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["setup-site"])


def test_version_flag_prints_version_and_exits(capsys):
    parser = safe_ftp._build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert safe_ftp.__version__ in captured.out


def test_setup_site_new_flags_parse():
    parser = safe_ftp._build_parser()
    args = parser.parse_args([
        "setup-site", "--name", "mysite", "--non-interactive",
        "--host", "ftp.example.com", "--port", "21", "--username", "user",
        "--ftp-password", "pw", "--master-password", "mpw",
        "--use-tls", "--allowed-dirs", "/public_html/",
        "--from-filezilla", "export.xml",
    ])
    assert args.non_interactive is True
    assert args.host == "ftp.example.com"
    assert args.ftp_password == "pw"
    assert args.master_password == "mpw"
    assert args.use_tls is True
    assert args.no_tls is False
    assert args.allowed_dirs == "/public_html/"
    assert args.from_filezilla == "export.xml"


def test_setup_site_use_tls_and_no_tls_are_mutually_exclusive():
    parser = safe_ftp._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["setup-site", "--name", "mysite", "--use-tls", "--no-tls"])


def test_deploy_accepts_expected_hash_flag():
    parser = safe_ftp._build_parser()
    args = parser.parse_args(["deploy", "--local", "a", "--remote", "b", "--expected-hash", "abc123"])
    assert args.expected_hash == "abc123"


def test_deploy_expected_hash_defaults_to_none():
    parser = safe_ftp._build_parser()
    args = parser.parse_args(["deploy", "--local", "a", "--remote", "b"])
    assert args.expected_hash is None


def test_list_new_flags_parse():
    parser = safe_ftp._build_parser()
    args = parser.parse_args([
        "list", "--remote-dir", "/public_html", "--type", "file",
        "--include", "*.php", "--exclude", "*.log", "--limit", "10",
        "--sort", "size", "--reverse", "--max-depth", "2",
    ])
    assert args.type == "file"
    assert args.include == "*.php"
    assert args.exclude == "*.log"
    assert args.limit == 10
    assert args.sort == "size"
    assert args.reverse is True
    assert args.max_depth == 2


def test_list_new_flags_have_sane_defaults():
    parser = safe_ftp._build_parser()
    args = parser.parse_args(["list", "--remote-dir", "/public_html"])
    assert args.type == "all"
    assert args.include is None
    assert args.exclude is None
    assert args.limit is None
    assert args.sort == "name"
    assert args.reverse is False
    assert args.max_depth is None


def test_every_flag_has_help_text():
    parser = safe_ftp._build_parser()
    missing = []
    for sub_parser in parser._subparsers._group_actions[0].choices.values():
        for action in sub_parser._actions:
            if action.option_strings and action.help is None:
                missing.append((sub_parser.prog, action.option_strings))
    assert missing == []


def test_top_level_help_shows_workflow_epilog(capsys):
    parser = safe_ftp._build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "setup-site --name mysite" in out
    assert "--execute" in out
