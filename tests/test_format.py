import safe_ftp_format as fmt


def test_format_deploy_markdown_success_shows_paths_and_backup():
    result = {
        "site": "mysite", "local_path": "/local/index.php", "remote_path": "/public_html/index.php",
        "executed": True, "status": "success", "message": "Backed up and uploaded.",
        "backup_name": "/public_html/index_270726_143210_482391.php",
    }
    md = fmt.format_deploy_markdown(result)
    assert "/local/index.php" in md
    assert "/public_html/index.php" in md
    assert "index_270726_143210_482391.php" in md
    assert "Success" in md


def test_format_deploy_markdown_stale_download_shows_hashes():
    result = {
        "site": "mysite", "local_path": "a", "remote_path": "b", "executed": False,
        "status": "stale_download", "message": "stale",
        "expected_hash": "aaaa1111bbbb2222", "current_remote_hash": "cccc3333dddd4444",
    }
    md = fmt.format_deploy_markdown(result)
    assert "Stale download" in md
    assert "aaaa1111" in md
    assert "cccc3333" in md


def test_format_download_markdown_shows_hash_when_present():
    result = {
        "site": "mysite", "remote_path": "/public_html/config.php", "local_path": "./config.php",
        "executed": True, "status": "success", "message": "Downloaded.",
        "local_backup_name": None, "hash": "abcdef1234567890",
    }
    md = fmt.format_download_markdown(result)
    assert "abcdef12" in md
    assert "/public_html/config.php" in md
    assert "./config.php" in md


def test_format_status_markdown_shows_drift_hashes():
    result = {
        "site": "mysite", "remote_path": "/public_html/index.php", "remote_exists": True,
        "status": "drift", "message": "Remote file has changed.",
        "current_remote_hash": "1111222233334444", "last_known_hash": "5555666677778888",
    }
    md = fmt.format_status_markdown(result)
    assert "1111222" in md
    assert "5555666" in md


def test_format_history_markdown_shows_entries_and_count():
    result = {
        "site": "mysite", "remote_path": "/public_html/index.php", "total_entries": 3,
        "entries": [
            {"deployed_at": "2026-08-01T14:32:10", "message": "fix bug",
             "new_hash": "abcdef1234567890", "backup_name": "/public_html/index_010826.php"},
            {"deployed_at": "2026-07-30T10:00:00", "message": "", "new_hash": "1111222233334444",
             "backup_name": None},
        ],
    }
    md = fmt.format_history_markdown(result)
    assert "fix bug" in md
    assert "abcdef12" in md
    assert "index_010826.php" in md
    assert "_(no message)_" in md
    assert "Showing 2 of 3" in md


def test_format_history_markdown_empty():
    result = {"site": "mysite", "remote_path": "/public_html/index.php", "total_entries": 0, "entries": []}
    md = fmt.format_history_markdown(result)
    assert "No recorded deploys" in md


def test_format_history_markdown_escapes_pipe_in_message():
    result = {
        "site": "mysite", "remote_path": "/public_html/index.php", "total_entries": 1,
        "entries": [
            {"deployed_at": "2026-08-01T14:32:10", "message": "a | b\nc", "new_hash": "aa", "backup_name": None},
        ],
    }
    md = fmt.format_history_markdown(result)
    assert "a \\| b c" in md


def test_format_list_remote_markdown_table_has_all_entries_and_summary():
    result = {
        "site": "mysite", "remote_dir": "/public_html", "status": "ok",
        "message": "2 entries in /public_html.",
        "entries": [
            {"name": "blog", "type": "dir", "size": None, "modify": None},
            {"name": "index.php", "type": "file", "size": "2048", "modify": "20260101120000"},
        ],
    }
    md = fmt.format_list_remote_markdown(result)
    assert "blog" in md
    assert "index.php" in md
    assert "2 entries" in md
    assert "1 dirs, 1 files" in md
    assert "2.0 KB" in md


def test_format_list_remote_markdown_shows_truncation():
    result = {
        "site": "mysite", "remote_dir": "/public_html", "status": "ok", "message": "1 entry.",
        "entries": [{"name": "a.txt", "type": "file", "size": "1", "modify": None}],
        "truncated": True, "total_matched": 50,
    }
    md = fmt.format_list_remote_markdown(result)
    assert "showing 1 of 50 matched" in md


def test_format_list_remote_markdown_blocked():
    result = {"site": "mysite", "remote_dir": "/etc", "status": "blocked", "message": "Refused.", "entries": []}
    md = fmt.format_list_remote_markdown(result)
    assert "Refused." in md


def test_format_batch_deploy_markdown_groups_changed_before_unchanged():
    results = [
        {"local_path": "/l/a.txt", "remote_path": "/r/a.txt", "status": "no_change", "message": "same"},
        {"local_path": "/l/b.txt", "remote_path": "/r/b.txt", "status": "dry_run", "message": "would deploy",
         "backup_name": "/r/b_270726.txt"},
    ]
    md = fmt.format_batch_deploy_markdown(results, "/l", "/r")
    assert "/l/a.txt" in md
    assert "/l/b.txt" in md
    assert "/r/a.txt" in md
    assert "/r/b.txt" in md
    assert "b_270726.txt" in md
    assert "1 file(s) will change" in md
    assert "1 unchanged" in md
    # The changed row (b.txt) appears before the unchanged row (a.txt).
    assert md.index("b.txt") < md.index("a.txt")


def test_format_batch_deploy_markdown_empty_results():
    md = fmt.format_batch_deploy_markdown([], "/l", "/r")
    assert "No files matched" in md


def test_format_batch_download_markdown_uses_local_backup_key():
    results = [
        {"local_path": "/l/config.php", "remote_path": "/r/config.php", "status": "success",
         "message": "downloaded", "local_backup_name": "/l/config_270726.php"},
    ]
    md = fmt.format_batch_download_markdown(results, "/r", "/l")
    assert "config_270726.php" in md
    assert "1 file(s) will change" in md


def test_format_setup_site_markdown_success():
    result = {
        "site": "mysite", "host": "ftp.example.com", "port": "21", "use_tls": True,
        "connection_ok": True, "connection_message": "Connected to ftp.example.com:21.",
        "allowed_remote_dirs": ["/public_html/"], "migrated_from_masterpwd": False,
        "creds_file": "/home/user/.safe_ftp_deploy/sites.enc",
    }
    md = fmt.format_setup_site_markdown(result)
    assert "mysite" in md
    assert "ftp.example.com:21" in md
    assert "FTPS" in md
    assert "Connection test: OK" in md
    assert "/public_html/" in md
    assert "Migrated" not in md


def test_format_setup_site_markdown_connection_failure_warns():
    result = {
        "site": "mysite", "host": "ftp.example.com", "port": "21", "use_tls": False,
        "connection_ok": False, "connection_message": "Could not connect: timed out",
        "allowed_remote_dirs": [], "migrated_from_masterpwd": True,
        "creds_file": "/home/user/.safe_ftp_deploy/sites.enc",
    }
    md = fmt.format_setup_site_markdown(result)
    assert "WARNING: connection test failed" in md
    assert "timed out" in md
    assert "WARNING: no allowed_remote_dirs set" in md
    assert "Migrated your master password into .ftpconfig" in md
