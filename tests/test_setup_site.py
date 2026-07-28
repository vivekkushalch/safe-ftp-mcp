import argparse

import safe_ftp


def _stub_setup_site_io(monkeypatch, master_password, ftp_password="ftppass"):
    """Feed cmd_setup_site's input()/getpass.getpass() calls with fixed values.
    Order of input() calls in cmd_setup_site: host, port, username,
    use_tls_in, allowed_dirs. getpass.getpass is called for the master
    password (via _get_master_password) and separately for the FTP password."""
    inputs = iter(["ftp.example.com", "21", "user", "y", "/public_html/"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr(
        safe_ftp.getpass,
        "getpass",
        lambda prompt="": master_password if "Master" in prompt else ftp_password,
    )


def _isolate_global_config(tmp_path, monkeypatch):
    config_dir = tmp_path / "global_config"
    monkeypatch.setattr(safe_ftp, "CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(safe_ftp, "CREDS_FILE", str(config_dir / "sites.enc"))
    monkeypatch.setattr(safe_ftp, "SALT_FILE", str(config_dir / "salt.bin"))


def test_setup_site_writes_ftpconfig(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)
    _stub_setup_site_io(monkeypatch, master_password="hunter2")

    safe_ftp.cmd_setup_site(argparse.Namespace(name="mysite"))

    lines = (tmp_path / ".ftpconfig").read_text(encoding="utf-8").splitlines()
    assert lines == ["mysite", "hunter2"]


def test_setup_site_migrates_legacy_masterpwd(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)
    (tmp_path / ".masterpwd").write_text("legacy-pw\n", encoding="utf-8")
    # No "Master" prompt stub needed for password sourcing -- _get_master_password
    # reads legacy-pw from .masterpwd before ever calling getpass for it.
    _stub_setup_site_io(monkeypatch, master_password="unused")

    safe_ftp.cmd_setup_site(argparse.Namespace(name="mysite"))

    lines = (tmp_path / ".ftpconfig").read_text(encoding="utf-8").splitlines()
    assert lines == ["mysite", "legacy-pw"]
    assert "Migrated your master password into .ftpconfig" in capsys.readouterr().out


def test_setup_site_no_migration_message_when_ftpconfig_already_existed(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)
    (tmp_path / ".ftpconfig").write_text("oldsite\nhunter2\n", encoding="utf-8")
    _stub_setup_site_io(monkeypatch, master_password="hunter2")

    safe_ftp.cmd_setup_site(argparse.Namespace(name="mysite"))

    assert "Migrated" not in capsys.readouterr().out
    lines = (tmp_path / ".ftpconfig").read_text(encoding="utf-8").splitlines()
    assert lines == ["mysite", "hunter2"]
