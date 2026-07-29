import hashlib

import safe_ftp


class _FakeFTP:
    """Minimal in-memory FTP double supporting exactly what deploy_file and
    download_file use: nlst, retrbinary, storbinary, rename, quit."""

    def __init__(self, files=None):
        self.files = dict(files or {})  # remote path -> bytes

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

    def quit(self):
        pass


def _isolate_state(tmp_path, monkeypatch):
    config_dir = tmp_path / "global_config"
    monkeypatch.setattr(safe_ftp, "CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(safe_ftp, "STATE_FILE", str(config_dir / "state.json"))


def _hash_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _site():
    return {"host": "ftp.example.com", "allowed_remote_dirs": []}


def test_deploy_proceeds_when_expected_hash_matches(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    local_file = tmp_path / "index.php"
    local_file.write_bytes(b"new content")
    remote_content = b"old content"
    fake_ftp = _FakeFTP(files={"/public_html/index.php": remote_content})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp.deploy_file(
        "mysite", _site(), str(local_file), "/public_html/index.php",
        execute=True, expected_hash=_hash_of(remote_content),
    )

    assert result["status"] == "success"
    assert fake_ftp.files["/public_html/index.php"] == b"new content"


def test_deploy_blocks_when_expected_hash_does_not_match(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    local_file = tmp_path / "index.php"
    local_file.write_bytes(b"new content")
    fake_ftp = _FakeFTP(files={"/public_html/index.php": b"changed by someone else"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp.deploy_file(
        "mysite", _site(), str(local_file), "/public_html/index.php",
        execute=True, expected_hash=_hash_of(b"old content"),
    )

    assert result["status"] == "stale_download"
    assert fake_ftp.files["/public_html/index.php"] == b"changed by someone else"


def test_deploy_stale_download_bypassed_by_force(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    local_file = tmp_path / "index.php"
    local_file.write_bytes(b"new content")
    fake_ftp = _FakeFTP(files={"/public_html/index.php": b"changed by someone else"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp.deploy_file(
        "mysite", _site(), str(local_file), "/public_html/index.php",
        execute=True, force=True, expected_hash=_hash_of(b"old content"),
    )

    assert result["status"] == "success"


def test_deploy_without_expected_hash_behaves_as_before(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    local_file = tmp_path / "index.php"
    local_file.write_bytes(b"new content")
    fake_ftp = _FakeFTP(files={"/public_html/index.php": b"old content"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp.deploy_file(
        "mysite", _site(), str(local_file), "/public_html/index.php", execute=True,
    )

    assert result["status"] == "success"


def test_download_result_includes_hash(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    local_file = tmp_path / "config.php"
    remote_content = b"remote content"
    fake_ftp = _FakeFTP(files={"/public_html/config.php": remote_content})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp.download_file(
        "mysite", _site(), "/public_html/config.php", str(local_file), execute=True,
    )

    assert result["status"] == "success"
    assert result["hash"] == _hash_of(remote_content)
