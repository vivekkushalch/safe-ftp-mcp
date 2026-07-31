import safe_ftp


class _ProgressFakeFTP:
    """FakeFTP that supports the extras show_progress=True needs: a
    callback= kwarg on storbinary, and a size() method (raises if
    remote_size wasn't given, simulating a server without SIZE support)."""

    def __init__(self, files=None, remote_size=None):
        self.files = dict(files or {})
        self.remote_size = remote_size
        self.storbinary_callback = None

    def nlst(self, directory):
        return list(self.files.keys())

    def retrbinary(self, cmd, callback):
        path = cmd.split(" ", 1)[1]
        callback(self.files[path])

    def storbinary(self, cmd, fileobj, callback=None):
        path = cmd.split(" ", 1)[1]
        data = fileobj.read()
        self.files[path] = data
        self.storbinary_callback = callback
        if callback:
            callback(data)

    def size(self, path):
        if self.remote_size is None:
            raise Exception("SIZE not supported")
        return self.remote_size

    def rename(self, old, new):
        self.files[new] = self.files.pop(old)

    def quit(self):
        pass


class _PlainFakeFTP:
    """FakeFTP with no callback/size support at all -- proves the
    show_progress=False (default) path never touches those APIs."""

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

    def quit(self):
        pass


def _isolate_state(tmp_path, monkeypatch):
    config_dir = tmp_path / "global_config"
    monkeypatch.setattr(safe_ftp, "CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(safe_ftp, "STATE_FILE", str(config_dir / "state.json"))
    monkeypatch.setattr(safe_ftp, "HISTORY_FILE", str(config_dir / "history.json"))


def _site():
    return {"host": "ftp.example.com", "allowed_remote_dirs": []}


def test_deploy_defaults_to_no_progress_and_works_with_plain_fake(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    local_file = tmp_path / "index.php"
    local_file.write_bytes(b"new content")
    fake_ftp = _PlainFakeFTP(files={"/public_html/index.php": b"old content"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp.deploy_file(
        "mysite", _site(), str(local_file), "/public_html/index.php", execute=True,
    )

    assert result["status"] == "success"
    assert fake_ftp.files["/public_html/index.php"] == b"new content"


def test_deploy_with_show_progress_true_passes_callback_and_still_succeeds(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    local_file = tmp_path / "index.php"
    local_file.write_bytes(b"new content")
    fake_ftp = _ProgressFakeFTP(files={"/public_html/index.php": b"old content"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp.deploy_file(
        "mysite", _site(), str(local_file), "/public_html/index.php",
        execute=True, show_progress=True,
    )

    assert result["status"] == "success"
    assert fake_ftp.files["/public_html/index.php"] == b"new content"
    assert fake_ftp.storbinary_callback is not None


def test_download_defaults_to_no_progress_and_works_with_plain_fake(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    local_file = tmp_path / "config.php"
    fake_ftp = _PlainFakeFTP(files={"/public_html/config.php": b"remote content"})
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp.download_file(
        "mysite", _site(), "/public_html/config.php", str(local_file), execute=True,
    )

    assert result["status"] == "success"
    assert local_file.read_bytes() == b"remote content"


def test_download_with_show_progress_true_uses_size_when_available(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    local_file = tmp_path / "config.php"
    fake_ftp = _ProgressFakeFTP(files={"/public_html/config.php": b"remote content"}, remote_size=14)
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp.download_file(
        "mysite", _site(), "/public_html/config.php", str(local_file), execute=True, show_progress=True,
    )

    assert result["status"] == "success"
    assert local_file.read_bytes() == b"remote content"


def test_download_with_show_progress_true_falls_back_when_size_unsupported(tmp_path, monkeypatch):
    _isolate_state(tmp_path, monkeypatch)
    local_file = tmp_path / "config.php"
    fake_ftp = _ProgressFakeFTP(files={"/public_html/config.php": b"remote content"})  # remote_size=None
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    result = safe_ftp.download_file(
        "mysite", _site(), "/public_html/config.php", str(local_file), execute=True, show_progress=True,
    )

    assert result["status"] == "success"
    assert local_file.read_bytes() == b"remote content"
