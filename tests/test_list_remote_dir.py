import safe_ftp


class _FakeListFTP:
    def __init__(self, mlsd_entries=None, nlst_entries=None, mlsd_supported=True, tree=None):
        self.mlsd_entries = mlsd_entries or []
        self.nlst_entries = nlst_entries or []
        self.mlsd_supported = mlsd_supported
        self.tree = tree or {}  # for recursive mode: {dir: [(name, facts), ...]}

    def mlsd(self, directory):
        if not self.mlsd_supported:
            raise Exception("MLSD not supported")
        if self.tree:
            return self.tree.get(directory, [])
        return self.mlsd_entries

    def nlst(self, directory):
        return self.nlst_entries

    def quit(self):
        pass


def _site(allowed_dirs=None):
    return {"host": "ftp.example.com", "allowed_remote_dirs": allowed_dirs or []}


def test_list_filters_by_type(monkeypatch):
    ftp = _FakeListFTP(mlsd_entries=[
        ("index.php", {"type": "file", "size": "10"}),
        ("blog", {"type": "dir"}),
    ])
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: ftp)

    result = safe_ftp.list_remote_dir("mysite", _site(), "/public_html", entry_type="dir")

    assert [e["name"] for e in result["entries"]] == ["blog"]


def test_list_include_exclude_glob_filters(monkeypatch):
    ftp = _FakeListFTP(mlsd_entries=[
        ("index.php", {"type": "file", "size": "10"}),
        ("style.css", {"type": "file", "size": "5"}),
        ("debug.log", {"type": "file", "size": "1"}),
    ])
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: ftp)

    result = safe_ftp.list_remote_dir(
        "mysite", _site(), "/public_html", include=["*.php", "*.css"], exclude=["debug.*"],
    )

    assert sorted(e["name"] for e in result["entries"]) == ["index.php", "style.css"]


def test_list_limit_truncates_and_reports_total(monkeypatch):
    ftp = _FakeListFTP(mlsd_entries=[(f"file{i}.txt", {"type": "file", "size": str(i)}) for i in range(5)])
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: ftp)

    result = safe_ftp.list_remote_dir("mysite", _site(), "/public_html", limit=2)

    assert len(result["entries"]) == 2
    assert result["truncated"] is True
    assert result["total_matched"] == 5


def test_list_no_truncation_when_under_limit(monkeypatch):
    ftp = _FakeListFTP(mlsd_entries=[("index.php", {"type": "file", "size": "10"})])
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: ftp)

    result = safe_ftp.list_remote_dir("mysite", _site(), "/public_html", limit=10)

    assert "truncated" not in result


def test_list_sort_by_size(monkeypatch):
    ftp = _FakeListFTP(mlsd_entries=[
        ("big.txt", {"type": "file", "size": "300"}),
        ("small.txt", {"type": "file", "size": "10"}),
        ("medium.txt", {"type": "file", "size": "100"}),
    ])
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: ftp)

    result = safe_ftp.list_remote_dir("mysite", _site(), "/public_html", sort_by="size")

    assert [e["name"] for e in result["entries"]] == ["small.txt", "medium.txt", "big.txt"]


def test_list_sort_reverse(monkeypatch):
    ftp = _FakeListFTP(mlsd_entries=[
        ("a.txt", {"type": "file", "size": "1"}),
        ("b.txt", {"type": "file", "size": "2"}),
    ])
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: ftp)

    result = safe_ftp.list_remote_dir("mysite", _site(), "/public_html", sort_by="name", reverse=True)

    assert [e["name"] for e in result["entries"]] == ["b.txt", "a.txt"]


def test_list_default_sort_puts_dirs_first(monkeypatch):
    ftp = _FakeListFTP(mlsd_entries=[
        ("zzz_file.txt", {"type": "file", "size": "1"}),
        ("aaa_dir", {"type": "dir"}),
    ])
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: ftp)

    result = safe_ftp.list_remote_dir("mysite", _site(), "/public_html")

    assert [e["name"] for e in result["entries"]] == ["aaa_dir", "zzz_file.txt"]


def test_list_recursive_preserves_size_and_modify(monkeypatch):
    ftp = _FakeListFTP(tree={
        "/public_html": [("index.php", {"type": "file", "size": "42", "modify": "20260101120000"})],
    })
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: ftp)

    result = safe_ftp.list_remote_dir("mysite", _site(), "/public_html", recursive=True)

    entry = result["entries"][0]
    assert entry["path"] == "/public_html/index.php"
    assert entry["size"] == "42"
    assert entry["modify"] == "20260101120000"


def test_list_recursive_respects_max_depth(monkeypatch):
    ftp = _FakeListFTP(tree={
        "/public_html": [("blog", {"type": "dir"}), ("index.php", {"type": "file", "size": "1"})],
        "/public_html/blog": [("post.php", {"type": "file", "size": "2"})],
    })
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: ftp)

    result = safe_ftp.list_remote_dir("mysite", _site(), "/public_html", recursive=True, max_depth=1)

    assert [e["path"] for e in result["entries"]] == ["/public_html/index.php"]


def test_list_flat_fallback_still_applies_filters_and_limit(monkeypatch):
    ftp = _FakeListFTP(mlsd_supported=False, nlst_entries=["/public_html/index.php", "/public_html/style.css"])
    monkeypatch.setattr(safe_ftp, "_connect", lambda site: ftp)

    result = safe_ftp.list_remote_dir("mysite", _site(), "/public_html", limit=1)

    assert result["status"] == "ok_flat"
    assert len(result["entries"]) == 1
    assert result["truncated"] is True
