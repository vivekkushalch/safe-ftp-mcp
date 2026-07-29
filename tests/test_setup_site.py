import argparse

import pytest

import safe_ftp


def _setup_args(**overrides):
    defaults = dict(
        name="mysite",
        non_interactive=False,
        from_filezilla=None,
        host=None,
        port=None,
        username=None,
        ftp_password=None,
        master_password=None,
        use_tls=False,
        no_tls=False,
        allowed_dirs=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _stub_setup_site_io(monkeypatch, master_password, ftp_password="ftppass"):
    """Feed cmd_setup_site's input()/getpass.getpass() calls with fixed values.
    Order of input() calls in cmd_setup_site: host, port, username,
    use_tls_in, allowed_dirs. getpass.getpass is called for the master
    password (via _resolve_master_password_for_setup) and separately for
    the FTP password (via _resolve_ftp_password_for_setup)."""
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


def _stub_connect(monkeypatch, succeed=True):
    """Stub the real network call cmd_setup_site now makes to test the
    connection. succeed=False simulates a connection failure."""

    class _FakeFTP:
        def quit(self):
            pass

    if succeed:
        monkeypatch.setattr(safe_ftp, "_connect", lambda site: _FakeFTP())
    else:
        def _raise(site):
            raise OSError("Connection refused")

        monkeypatch.setattr(safe_ftp, "_connect", _raise)


def test_setup_site_writes_ftpconfig(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)
    _stub_setup_site_io(monkeypatch, master_password="hunter2")
    _stub_connect(monkeypatch)

    safe_ftp.cmd_setup_site(_setup_args())

    lines = (tmp_path / ".ftpconfig").read_text(encoding="utf-8").splitlines()
    assert lines == ["mysite", "hunter2"]


def test_setup_site_migrates_legacy_masterpwd(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)
    (tmp_path / ".masterpwd").write_text("legacy-pw\n", encoding="utf-8")
    _stub_setup_site_io(monkeypatch, master_password="unused")
    _stub_connect(monkeypatch)

    safe_ftp.cmd_setup_site(_setup_args())

    lines = (tmp_path / ".ftpconfig").read_text(encoding="utf-8").splitlines()
    assert lines == ["mysite", "legacy-pw"]
    assert "Migrated your master password into .ftpconfig" in capsys.readouterr().out


def test_setup_site_no_migration_message_when_ftpconfig_already_existed(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)
    (tmp_path / ".ftpconfig").write_text("oldsite\nhunter2\n", encoding="utf-8")
    _stub_setup_site_io(monkeypatch, master_password="hunter2")
    _stub_connect(monkeypatch)

    safe_ftp.cmd_setup_site(_setup_args())

    assert "Migrated" not in capsys.readouterr().out
    lines = (tmp_path / ".ftpconfig").read_text(encoding="utf-8").splitlines()
    assert lines == ["mysite", "hunter2"]


def test_setup_site_fully_non_interactive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("should not prompt"))
    )
    monkeypatch.setattr(
        safe_ftp.getpass, "getpass", lambda prompt="": (_ for _ in ()).throw(AssertionError("should not prompt"))
    )
    _stub_connect(monkeypatch)

    safe_ftp.cmd_setup_site(_setup_args(
        non_interactive=True,
        master_password="hunter2",
        host="ftp.example.com",
        port="21",
        username="user",
        ftp_password="ftppass",
        use_tls=True,
        allowed_dirs="/public_html/",
    ))

    lines = (tmp_path / ".ftpconfig").read_text(encoding="utf-8").splitlines()
    assert lines == ["mysite", "hunter2"]
    sites = safe_ftp._load_all_sites("hunter2")
    assert sites["mysite"]["host"] == "ftp.example.com"
    assert sites["mysite"]["allowed_remote_dirs"] == ["/public_html/"]


def test_setup_site_non_interactive_missing_field_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)

    with pytest.raises(SystemExit, match="--host"):
        safe_ftp.cmd_setup_site(_setup_args(
            non_interactive=True,
            master_password="hunter2",
            username="user",
            ftp_password="ftppass",
        ))


def test_setup_site_from_filezilla_standalone_interactive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)

    export_path = tmp_path / "export.xml"
    export_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<FileZilla3><Servers><Server>
    <Host>ftp.imported.com</Host>
    <Port>21</Port>
    <Protocol>0</Protocol>
    <User>importeduser</User>
    <Pass>importedpass</Pass>
</Server></Servers></FileZilla3>
""",
        encoding="utf-8",
    )

    # Only allowed_dirs should prompt -- host/port/username/password/use_tls
    # all come from the FileZilla export.
    monkeypatch.setattr("builtins.input", lambda prompt="": "/public_html/")
    monkeypatch.setattr(safe_ftp.getpass, "getpass", lambda prompt="": "hunter2")
    _stub_connect(monkeypatch)

    safe_ftp.cmd_setup_site(_setup_args(from_filezilla=str(export_path)))

    sites = safe_ftp._load_all_sites("hunter2")
    assert sites["mysite"]["host"] == "ftp.imported.com"
    assert sites["mysite"]["username"] == "importeduser"
    assert sites["mysite"]["password"] == "importedpass"
    assert sites["mysite"]["use_tls"] is False
    assert sites["mysite"]["allowed_remote_dirs"] == ["/public_html/"]


def test_setup_site_explicit_flag_overrides_filezilla_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)

    export_path = tmp_path / "export.xml"
    export_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<FileZilla3><Servers><Server>
    <Host>ftp.imported.com</Host>
    <User>importeduser</User>
    <Pass>importedpass</Pass>
</Server></Servers></FileZilla3>
""",
        encoding="utf-8",
    )
    _stub_connect(monkeypatch)

    safe_ftp.cmd_setup_site(_setup_args(
        non_interactive=True,
        master_password="hunter2",
        from_filezilla=str(export_path),
        host="override.example.com",
        ftp_password="overridepass",
        allowed_dirs="/public_html/",
    ))

    sites = safe_ftp._load_all_sites("hunter2")
    assert sites["mysite"]["host"] == "override.example.com"
    assert sites["mysite"]["username"] == "importeduser"
    assert sites["mysite"]["password"] == "overridepass"


def test_setup_site_prints_connection_success(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)
    _stub_setup_site_io(monkeypatch, master_password="hunter2")
    _stub_connect(monkeypatch, succeed=True)

    safe_ftp.cmd_setup_site(_setup_args())

    out = capsys.readouterr().out
    assert "Connection test" in out
    assert "OK" in out
    assert "WARNING: connection test failed" not in out


def test_setup_site_warns_on_connection_failure_but_still_saves(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _isolate_global_config(tmp_path, monkeypatch)
    _stub_setup_site_io(monkeypatch, master_password="hunter2")
    _stub_connect(monkeypatch, succeed=False)

    safe_ftp.cmd_setup_site(_setup_args())

    out = capsys.readouterr().out
    assert "WARNING: connection test failed" in out
    sites = safe_ftp._load_all_sites("hunter2")
    assert "mysite" in sites
