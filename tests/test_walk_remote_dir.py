import safe_ftp


class _FakeMLSDFTP:
    """Fake FTP supporting only mlsd(), for testing _walk_remote_dir."""

    def __init__(self, tree):
        self.tree = tree  # {"/dir": [(name, facts), ...]}

    def mlsd(self, directory):
        return self.tree[directory]


def test_walk_remote_dir_yields_facts_for_files():
    ftp = _FakeMLSDFTP({
        "/public_html": [("index.php", {"type": "file", "size": "1234", "modify": "20260101120000"})],
    })

    results = list(safe_ftp._walk_remote_dir(ftp, "/public_html"))

    assert results == [("/public_html/index.php", {"type": "file", "size": "1234", "modify": "20260101120000"})]


def test_walk_remote_dir_recurses_into_subdirectories():
    ftp = _FakeMLSDFTP({
        "/public_html": [("blog", {"type": "dir"}), ("index.php", {"type": "file", "size": "10"})],
        "/public_html/blog": [("post.php", {"type": "file", "size": "20"})],
    })

    results = list(safe_ftp._walk_remote_dir(ftp, "/public_html"))

    paths = sorted(path for path, _facts in results)
    assert paths == ["/public_html/blog/post.php", "/public_html/index.php"]


def test_walk_remote_dir_respects_max_depth():
    ftp = _FakeMLSDFTP({
        "/a": [("b", {"type": "dir"})],
        "/a/b": [("c.txt", {"type": "file", "size": "1"})],
    })

    # max_depth=1: only /a's direct children -- no recursion into "b".
    assert list(safe_ftp._walk_remote_dir(ftp, "/a", max_depth=1)) == []

    # max_depth=2: one level of recursion into "b" is allowed.
    results = list(safe_ftp._walk_remote_dir(ftp, "/a", max_depth=2))
    assert [path for path, _facts in results] == ["/a/b/c.txt"]


def test_walk_remote_dir_falls_back_to_nlst_when_mlsd_unsupported():
    class _FakeNLSTFTP:
        def mlsd(self, directory):
            raise Exception("MLSD not supported")

        def nlst(self, directory):
            return ["/public_html/index.php", "/public_html/style.css"]

    results = list(safe_ftp._walk_remote_dir(_FakeNLSTFTP(), "/public_html"))

    assert results == [
        ("/public_html/index.php", {}),
        ("/public_html/style.css", {}),
    ]
