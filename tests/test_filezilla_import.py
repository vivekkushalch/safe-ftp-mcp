import base64

import pytest

import safe_ftp


def _write_export(tmp_path, servers_xml, filename="export.xml"):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<FileZilla3 version="3.66.4" platform="windows">
    <Servers>
{servers_xml}
    </Servers>
</FileZilla3>
"""
    path = tmp_path / filename
    path.write_text(xml, encoding="utf-8")
    return str(path)


def _server_block(host="ftp.example.com", port="21", username="myuser",
                   pass_text="plainpassword", pass_encoding=None, protocol=None):
    pass_attr = f' encoding="{pass_encoding}"' if pass_encoding else ""
    protocol_line = f"            <Protocol>{protocol}</Protocol>\n" if protocol is not None else ""
    return f"""        <Server>
            <Host>{host}</Host>
            <Port>{port}</Port>
{protocol_line}            <User>{username}</User>
            <Pass{pass_attr}>{pass_text}</Pass>
        </Server>"""


def test_parses_plain_password(tmp_path):
    path = _write_export(tmp_path, _server_block(pass_text="plainpassword"))
    result = safe_ftp._parse_filezilla_export(path)
    assert result == {
        "host": "ftp.example.com",
        "port": "21",
        "username": "myuser",
        "password": "plainpassword",
        "use_tls": None,
    }


def test_parses_base64_password(tmp_path):
    encoded = base64.b64encode(b"mypassword").decode("ascii")
    path = _write_export(tmp_path, _server_block(pass_text=encoded, pass_encoding="base64"))
    result = safe_ftp._parse_filezilla_export(path)
    assert result["password"] == "mypassword"


def test_crypt_encoding_errors_clearly(tmp_path):
    path = _write_export(tmp_path, _server_block(pass_text="unreadable-blob", pass_encoding="crypt"))
    with pytest.raises(SystemExit, match="master-password-protected"):
        safe_ftp._parse_filezilla_export(path)


def test_zero_servers_errors(tmp_path):
    path = _write_export(tmp_path, "")
    with pytest.raises(SystemExit, match="No <Server>"):
        safe_ftp._parse_filezilla_export(path)


def test_multiple_servers_errors(tmp_path):
    path = _write_export(tmp_path, _server_block() + "\n" + _server_block(host="ftp2.example.com"))
    with pytest.raises(SystemExit, match="contains 2 sites"):
        safe_ftp._parse_filezilla_export(path)


def test_sftp_protocol_errors(tmp_path):
    path = _write_export(tmp_path, _server_block(protocol=1))
    with pytest.raises(SystemExit, match="SFTP"):
        safe_ftp._parse_filezilla_export(path)


def test_plain_ftp_protocol_maps_to_no_tls(tmp_path):
    path = _write_export(tmp_path, _server_block(protocol=0))
    result = safe_ftp._parse_filezilla_export(path)
    assert result["use_tls"] is False


def test_ftpes_protocol_maps_to_tls(tmp_path):
    path = _write_export(tmp_path, _server_block(protocol=6))
    result = safe_ftp._parse_filezilla_export(path)
    assert result["use_tls"] is True


def test_unrecognized_protocol_leaves_use_tls_none(tmp_path):
    path = _write_export(tmp_path, _server_block(protocol=99))
    result = safe_ftp._parse_filezilla_export(path)
    assert result["use_tls"] is None
