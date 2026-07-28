import argparse

import pytest

import safe_ftp


def test_read_ftpconfig_missing_file_returns_none_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert safe_ftp._read_ftpconfig() == (None, None)


def test_read_ftpconfig_returns_both_lines_trimmed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ftpconfig").write_text("mysite \n hunter2 \n", encoding="utf-8")
    assert safe_ftp._read_ftpconfig() == ("mysite", "hunter2")


def test_read_ftpconfig_missing_second_line_returns_none_password(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ftpconfig").write_text("mysite\n", encoding="utf-8")
    assert safe_ftp._read_ftpconfig() == ("mysite", None)


def test_get_master_password_uses_ftpconfig_when_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ftpconfig").write_text("mysite\nfrom-ftpconfig\n", encoding="utf-8")
    monkeypatch.setattr(
        safe_ftp.getpass, "getpass", lambda prompt="": (_ for _ in ()).throw(AssertionError("should not prompt"))
    )
    assert safe_ftp._get_master_password("Master password: ") == "from-ftpconfig"


def test_get_master_password_falls_back_to_legacy_masterpwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".masterpwd").write_text("from-masterpwd\n", encoding="utf-8")
    monkeypatch.setattr(
        safe_ftp.getpass, "getpass", lambda prompt="": (_ for _ in ()).throw(AssertionError("should not prompt"))
    )
    assert safe_ftp._get_master_password("Master password: ") == "from-masterpwd"


def test_get_master_password_falls_back_to_getpass_prompt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(safe_ftp.getpass, "getpass", lambda prompt="": "typed-password")
    assert safe_ftp._get_master_password("Master password: ") == "typed-password"


def test_resolve_site_name_explicit_name_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ftpconfig").write_text("configsite\npw\n", encoding="utf-8")
    args = argparse.Namespace(name="clisite")
    assert safe_ftp._resolve_site_name(args) == "clisite"


def test_resolve_site_name_falls_back_to_ftpconfig(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ftpconfig").write_text("configsite\npw\n", encoding="utf-8")
    args = argparse.Namespace(name=None)
    assert safe_ftp._resolve_site_name(args) == "configsite"


def test_resolve_site_name_errors_when_neither_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(name=None)
    with pytest.raises(SystemExit):
        safe_ftp._resolve_site_name(args)
