import safe_ftp


def test_module_is_importable_and_has_version():
    assert hasattr(safe_ftp, "__version__")
    assert isinstance(safe_ftp.__version__, str)
    assert safe_ftp.__version__


def test_main_is_callable():
    assert callable(safe_ftp.main)
