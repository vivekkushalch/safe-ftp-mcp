import argparse

import pytest

import safe_ftp


def _args(**overrides):
    defaults = dict(
        non_interactive=False,
        master_password=None,
        ftp_password=None,
        host=None,
        port=None,
        username=None,
        use_tls=False,
        no_tls=False,
        allowed_dirs=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_master_password_flag_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SAFE_FTP_MASTER_PASSWORD", "from-env")
    (tmp_path / ".ftpconfig").write_text("site\nfrom-ftpconfig\n", encoding="utf-8")
    args = _args(master_password="from-flag")
    assert safe_ftp._resolve_master_password_for_setup(args) == "from-flag"


def test_master_password_env_wins_over_ftpconfig(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SAFE_FTP_MASTER_PASSWORD", "from-env")
    (tmp_path / ".ftpconfig").write_text("site\nfrom-ftpconfig\n", encoding="utf-8")
    args = _args()
    assert safe_ftp._resolve_master_password_for_setup(args) == "from-env"


def test_master_password_falls_back_to_ftpconfig(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SAFE_FTP_MASTER_PASSWORD", raising=False)
    (tmp_path / ".ftpconfig").write_text("site\nfrom-ftpconfig\n", encoding="utf-8")
    args = _args()
    assert safe_ftp._resolve_master_password_for_setup(args) == "from-ftpconfig"


def test_master_password_non_interactive_errors_when_unresolved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SAFE_FTP_MASTER_PASSWORD", raising=False)
    args = _args(non_interactive=True)
    with pytest.raises(SystemExit, match="master password"):
        safe_ftp._resolve_master_password_for_setup(args)


def test_master_password_interactive_falls_back_to_prompt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SAFE_FTP_MASTER_PASSWORD", raising=False)
    monkeypatch.setattr(safe_ftp.getpass, "getpass", lambda prompt="": "typed-password")
    args = _args(non_interactive=False)
    assert safe_ftp._resolve_master_password_for_setup(args) == "typed-password"


def test_ftp_password_flag_wins(monkeypatch):
    monkeypatch.setenv("SAFE_FTP_FTP_PASSWORD", "from-env")
    args = _args(ftp_password="from-flag")
    assert safe_ftp._resolve_ftp_password_for_setup(args, imported_password="from-import") == "from-flag"


def test_ftp_password_env_wins_over_import(monkeypatch):
    monkeypatch.setenv("SAFE_FTP_FTP_PASSWORD", "from-env")
    args = _args()
    assert safe_ftp._resolve_ftp_password_for_setup(args, imported_password="from-import") == "from-env"


def test_ftp_password_falls_back_to_import(monkeypatch):
    monkeypatch.delenv("SAFE_FTP_FTP_PASSWORD", raising=False)
    args = _args()
    assert safe_ftp._resolve_ftp_password_for_setup(args, imported_password="from-import") == "from-import"


def test_ftp_password_non_interactive_errors_when_unresolved(monkeypatch):
    monkeypatch.delenv("SAFE_FTP_FTP_PASSWORD", raising=False)
    args = _args(non_interactive=True)
    with pytest.raises(SystemExit, match="FTP password"):
        safe_ftp._resolve_ftp_password_for_setup(args, imported_password=None)


def test_ftp_password_interactive_falls_back_to_prompt(monkeypatch):
    monkeypatch.delenv("SAFE_FTP_FTP_PASSWORD", raising=False)
    monkeypatch.setattr(safe_ftp.getpass, "getpass", lambda prompt="": "typed-ftp-password")
    args = _args(non_interactive=False)
    assert safe_ftp._resolve_ftp_password_for_setup(args, imported_password=None) == "typed-ftp-password"


def test_required_field_explicit_wins():
    args = _args(non_interactive=True)
    assert safe_ftp._resolve_required_field("explicit", "imported", "--host", args, "prompt: ") == "explicit"


def test_required_field_falls_back_to_imported():
    args = _args(non_interactive=True)
    assert safe_ftp._resolve_required_field(None, "imported", "--host", args, "prompt: ") == "imported"


def test_required_field_non_interactive_errors_when_unresolved():
    args = _args(non_interactive=True)
    with pytest.raises(SystemExit, match="--host"):
        safe_ftp._resolve_required_field(None, None, "--host", args, "prompt: ")


def test_required_field_interactive_prompts(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "typed-value")
    args = _args(non_interactive=False)
    assert safe_ftp._resolve_required_field(None, None, "--host", args, "prompt: ") == "typed-value"


def test_port_flag_wins():
    args = _args(port="2121")
    assert safe_ftp._resolve_port(args, imported_port="21") == "2121"


def test_port_falls_back_to_imported():
    args = _args()
    assert safe_ftp._resolve_port(args, imported_port="2200") == "2200"


def test_port_non_interactive_defaults_to_21():
    args = _args(non_interactive=True)
    assert safe_ftp._resolve_port(args, imported_port=None) == "21"


def test_port_interactive_prompts_with_default(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    args = _args(non_interactive=False)
    assert safe_ftp._resolve_port(args, imported_port=None) == "21"


def test_use_tls_flag_wins_over_import():
    args = _args(use_tls=True)
    assert safe_ftp._resolve_use_tls(args, imported_use_tls=False) is True


def test_no_tls_flag_wins_over_import():
    args = _args(no_tls=True)
    assert safe_ftp._resolve_use_tls(args, imported_use_tls=True) is False


def test_use_tls_falls_back_to_import():
    args = _args()
    assert safe_ftp._resolve_use_tls(args, imported_use_tls=False) is False


def test_use_tls_non_interactive_defaults_true():
    args = _args(non_interactive=True)
    assert safe_ftp._resolve_use_tls(args, imported_use_tls=None) is True


def test_use_tls_interactive_prompts(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    args = _args(non_interactive=False)
    assert safe_ftp._resolve_use_tls(args, imported_use_tls=None) is False


def test_allowed_dirs_flag_parses_csv():
    args = _args(allowed_dirs="/public_html/,/public_html/blog/")
    assert safe_ftp._resolve_allowed_dirs(args) == ["/public_html/", "/public_html/blog/"]


def test_allowed_dirs_non_interactive_defaults_empty():
    args = _args(non_interactive=True)
    assert safe_ftp._resolve_allowed_dirs(args) == []


def test_allowed_dirs_interactive_prompts(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "/public_html/")
    args = _args(non_interactive=False)
    assert safe_ftp._resolve_allowed_dirs(args) == ["/public_html/"]
