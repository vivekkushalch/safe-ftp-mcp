import safe_ftp
import safe_ftp_mcp


class _FakeFTP:
    def __init__(self, files=None):
        self.files = dict(files or {})

    def nlst(self, directory):
        return list(self.files.keys())

    def retrbinary(self, cmd, callback):
        path = cmd.split(" ", 1)[1]
        callback(self.files[path])

    def storbinary(self, cmd, fileobj):
        path = cmd.split(" ", 1)[1]
        self.files[path] = fileobj.read()

    def rename(self, old, new):
        self.files[new] = self.files.pop(old)

    def mlsd(self, directory):
        entries = []
        seen = set()
        prefix = directory.rstrip("/") + "/"
        for path in self.files:
            if not path.startswith(prefix):
                continue
            rest = path[len(prefix):]
            name = rest.split("/", 1)[0]
            if name in seen:
                continue
            seen.add(name)
            entries.append((name, {"type": "file", "size": str(len(self.files[path]))}))
        return entries

    def quit(self):
        pass


def _isolate(tmp_path, monkeypatch):
    config_dir = tmp_path / "global_config"
    monkeypatch.setattr(safe_ftp, "CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(safe_ftp, "CREDS_FILE", str(config_dir / "sites.enc"))
    monkeypatch.setattr(safe_ftp, "SALT_FILE", str(config_dir / "salt.bin"))
    monkeypatch.setattr(safe_ftp, "STATE_FILE", str(config_dir / "state.json"))


def _setup_configured_site(tmp_path, monkeypatch, site_name="mysite"):
    """Write .ftpconfig + encrypted sites.enc directly, bypassing
    cmd_setup_site, so tests don't need to fake interactive input just to
    get a usable site on disk."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    site = {
        "host": "ftp.example.com", "port": "21", "username": "user", "password": "ftppass",
        "use_tls": True, "allowed_remote_dirs": [],
    }
    safe_ftp._save_all_sites({site_name: site}, "hunter2")
    safe_ftp._write_ftpconfig(site_name, "hunter2")


def test_deploy_impl_defaults_to_dry_run(tmp_path, monkeypatch):
    _setup_configured_site(tmp_path, monkeypatch)
    local_file = tmp_path / "index.php"
    local_file.write_bytes(b"content")
    fake_ftp = _FakeFTP(files={"/public_html/index.php": b"old"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp_mcp._deploy_impl(local=str(local_file), remote="/public_html/index.php")

    assert result["status"] == "dry_run"
    assert result["summary_markdown"]
    assert fake_ftp.files["/public_html/index.php"] == b"old"


def test_deploy_impl_executes_when_asked(tmp_path, monkeypatch):
    _setup_configured_site(tmp_path, monkeypatch)
    local_file = tmp_path / "index.php"
    local_file.write_bytes(b"new content")
    fake_ftp = _FakeFTP(files={"/public_html/index.php": b"old content"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp_mcp._deploy_impl(local=str(local_file), remote="/public_html/index.php", execute=True)

    assert result["status"] == "success"
    assert fake_ftp.files["/public_html/index.php"] == b"new content"


def test_deploy_impl_returns_error_dict_when_no_site_configured(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = safe_ftp_mcp._deploy_impl(local="a", remote="b")

    assert result["status"] == "error"
    assert "message" in result


def test_download_impl_includes_summary_markdown(tmp_path, monkeypatch):
    _setup_configured_site(tmp_path, monkeypatch)
    local_file = tmp_path / "config.php"
    fake_ftp = _FakeFTP(files={"/public_html/config.php": b"remote content"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp_mcp._download_impl(remote="/public_html/config.php", local=str(local_file))

    assert result["status"] == "dry_run"
    assert result["summary_markdown"]


def test_status_impl_returns_summary(tmp_path, monkeypatch):
    _setup_configured_site(tmp_path, monkeypatch)
    fake_ftp = _FakeFTP(files={"/public_html/index.php": b"content"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp_mcp._status_impl(remote="/public_html/index.php")

    assert "summary_markdown" in result


def test_list_remote_impl_returns_summary_and_entries(tmp_path, monkeypatch):
    _setup_configured_site(tmp_path, monkeypatch)
    fake_ftp = _FakeFTP(files={"/public_html/index.php": b"content"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp_mcp._list_remote_impl(remote_dir="/public_html")

    assert result["status"] == "ok"
    assert len(result["entries"]) == 1
    assert result["summary_markdown"]


def test_batch_deploy_impl_returns_results_and_summary(tmp_path, monkeypatch):
    _setup_configured_site(tmp_path, monkeypatch)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "index.php").write_text("content", encoding="utf-8")
    fake_ftp = _FakeFTP()
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp_mcp._batch_deploy_impl(local_dir=str(src_dir), remote_dir="/public_html")

    assert len(result["results"]) == 1
    assert result["summary_markdown"]


def test_batch_download_impl_returns_results_and_summary(tmp_path, monkeypatch):
    _setup_configured_site(tmp_path, monkeypatch)
    local_dir = tmp_path / "dest"
    fake_ftp = _FakeFTP(files={"/public_html/index.php": b"content"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp_mcp._batch_download_impl(remote_dir="/public_html", local_dir=str(local_dir))

    assert len(result["results"]) == 1
    assert result["summary_markdown"]


def test_setup_site_impl_non_interactive_success(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)

    class _ConnectableFakeFTP:
        def quit(self):
            pass

    monkeypatch.setattr(safe_ftp, "_connect", lambda site: _ConnectableFakeFTP())

    result = safe_ftp_mcp._setup_site_impl(
        name="mysite", host="ftp.example.com", port="21", username="user",
        ftp_password="ftppass", master_password="hunter2", use_tls=True,
        allowed_dirs="/public_html/",
    )

    assert result["connection_ok"] is True
    assert result["summary_markdown"]
    sites = safe_ftp._load_all_sites("hunter2")
    assert sites["mysite"]["host"] == "ftp.example.com"


def test_setup_site_impl_missing_required_field_returns_error_dict(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = safe_ftp_mcp._setup_site_impl(
        name="mysite", username="user", ftp_password="pw", master_password="hunter2",
    )

    assert result["status"] == "error"
    assert "host" in result["message"].lower()
