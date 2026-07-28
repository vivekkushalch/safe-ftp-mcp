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
