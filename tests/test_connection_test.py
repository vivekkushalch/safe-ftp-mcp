import safe_ftp


class _FakeFTP:
    def __init__(self, quit_ok=True):
        self.quit_ok = quit_ok
        self.quit_called = False
        self.close_called = False

    def quit(self):
        self.quit_called = True
        if not self.quit_ok:
            raise Exception("quit failed")

    def close(self):
        self.close_called = True


def test_connection_test_succeeds(monkeypatch):
    fake_ftp = _FakeFTP()
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    ok, message = safe_ftp._test_site_connection({"host": "ftp.example.com", "port": "21"})

    assert ok is True
    assert "ftp.example.com" in message
    assert fake_ftp.quit_called is True


def test_connection_test_fails(monkeypatch):
    def _raise(site):
        raise OSError("Connection refused")

    monkeypatch.setattr(safe_ftp, "_connect", _raise)

    ok, message = safe_ftp._test_site_connection({"host": "ftp.example.com", "port": "21"})

    assert ok is False
    assert "Connection refused" in message


def test_connection_test_handles_quit_failure_gracefully(monkeypatch):
    fake_ftp = _FakeFTP(quit_ok=False)
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: fake_ftp)

    ok, message = safe_ftp._test_site_connection({"host": "ftp.example.com", "port": "21"})

    assert ok is True
    assert fake_ftp.close_called is True
