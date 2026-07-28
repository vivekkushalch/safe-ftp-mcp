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
