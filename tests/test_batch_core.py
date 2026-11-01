import pytest

import safe_ftp


class _FakeFTP:
    """Supports what batch_deploy_files/batch_download_files need: nlst,
    retrbinary, storbinary, rename, mlsd (for _walk_remote_dir), quit, cwd."""

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

    def cwd(self, directory):
        pass

    def quit(self):
        pass


def _isolate_state(tmp_path, monkeypatch):
    config_dir = tmp_path / "global_config"
    monkeypatch.setattr(safe_ftp, "CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(safe_ftp, "STATE_FILE", str(config_dir / "state.json"))
    monkeypatch.setattr(safe_ftp, "HISTORY_FILE", str(config_dir / "history.json"))


def _site():
    return {"host": "ftp.example.com", "allowed_remote_dirs": []}


def test_resolve_site_name_value_explicit_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ftpconfig").write_text("configsite\npw\n", encoding="utf-8")
    assert safe_ftp._resolve_site_name_value("clisite") == "clisite"


def test_resolve_site_name_value_falls_back_to_ftpconfig(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".ftpconfig").write_text("configsite\npw\n", encoding="utf-8")
    assert safe_ftp._resolve_site_name_value(None) == "configsite"


def test_resolve_site_name_value_errors_when_neither_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        safe_ftp._resolve_site_name_value(None)


def test_batch_deploy_files_deploys_matching_files(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    (tmp_path / "index.php").write_text("new", encoding="utf-8")
    (tmp_path / "readme.md").write_text("skip me", encoding="utf-8")
    fake_ftp = _FakeFTP()
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    results = safe_ftp.batch_deploy_files(
        "mysite", _site(), str(tmp_path), "/public_html", include=["*.php"], execute=True,
    )

    assert len(results) == 1
    assert results[0]["remote_path"] == "/public_html/index.php"
    assert results[0]["status"] == "success"


def test_batch_download_files_downloads_matching_files(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    local_dir = tmp_path / "dest"
    fake_ftp = _FakeFTP(files={"/public_html/index.php": b"remote content"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    results = safe_ftp.batch_download_files(
        "mysite", _site(), "/public_html", str(local_dir), execute=True,
    )

    assert len(results) == 1
    assert results[0]["status"] == "success"
    assert (local_dir / "index.php").read_bytes() == b"remote content"
