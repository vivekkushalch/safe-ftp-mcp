import ssl

import pytest

import safe_ftp


def test_context_verifies_by_default():
    ctx = safe_ftp._tls_context({})
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_context_verifies_when_flag_true():
    ctx = safe_ftp._tls_context({"verify_tls": True})
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_context_opt_out_disables_verification():
    ctx = safe_ftp._tls_context({"verify_tls": False})
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_connect_passes_verifying_context(monkeypatch):
    seen = {}

    class _FakeTLS:
        def __init__(self, context=None):
            seen["context"] = context

        def connect(self, *a, **k): pass
        def login(self, *a, **k): pass
        def prot_p(self): pass

    monkeypatch.setattr(safe_ftp, "FTP_TLS", _FakeTLS)
    safe_ftp._connect({"host": "h", "username": "u", "password": "p", "use_tls": True})
    assert seen["context"].verify_mode == ssl.CERT_REQUIRED


def test_cert_failure_message_points_to_insecure_tls(monkeypatch):
    def _raise(site):
        raise ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate")

    monkeypatch.setattr(safe_ftp, "_connect", _raise)
    ok, message = safe_ftp._test_site_connection({"host": "h"})
    assert ok is False
    assert "--insecure-tls" in message


def test_setup_site_flag_parses():
    args = safe_ftp._build_parser().parse_args(["setup-site", "--name", "x", "--insecure-tls"])
    assert args.insecure_tls is True
