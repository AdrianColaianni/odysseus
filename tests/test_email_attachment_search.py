import sqlite3
from email.message import EmailMessage


def test_attachment_filename_is_part_of_ui_index_search(tmp_path, monkeypatch):
    from routes.email import email_helpers, email_routes

    db_path = tmp_path / "mail.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE email_message_index (
        owner TEXT, account_key TEXT, folder TEXT, uid TEXT, message_id TEXT,
        subject TEXT, from_name TEXT, from_address TEXT, to_text TEXT, cc_text TEXT,
        date_iso TEXT, date_display TEXT, date_epoch REAL, size INTEGER, flags TEXT,
        has_attachments INTEGER, attachment_names TEXT, updated_at TEXT)"""
    )
    conn.execute(
        "INSERT INTO email_message_index VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("felix", "acct", "INBOX", "7", "<7@example>", "Quarterly files", "A", "a@example.com",
         "felix@example.com", "", "", "", 1, 10, "", 1, "PDPUK-tax-return.pdf", "now"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(email_helpers, "SCHEDULED_DB", db_path)

    rows, total, _ = email_routes._email_index_search(
        "felix", "acct", "INBOX", "PDPUK-tax", 20, global_search=False
    )

    assert total == 1
    assert rows[0]["uid"] == "7"


def test_signature_only_message_has_no_visible_attachments():
    from routes.email.email_helpers import _has_visible_attachments

    msg = EmailMessage()
    msg.set_content("Regards")
    msg.add_related(
        b"tiny-logo",
        maintype="image",
        subtype="png",
        cid="logo",
        filename="signature.png",
        disposition="inline",
    )

    assert _has_visible_attachments(msg) is False


def test_header_only_related_message_is_not_marked_as_attached():
    from routes.email.email_routes import _parse_email_list_record

    raw = (
        b"Content-Type: multipart/related; boundary=abc\r\n"
        b"Subject: Signature only\r\nFrom: a@example.com\r\n\r\n"
    )
    parsed = _parse_email_list_record(b"1 (UID 9 FLAGS () RFC822.SIZE 123)", raw)
    assert parsed["has_attachments"] is False


def test_real_attachment_remains_visible_alongside_signature():
    from routes.email.email_helpers import _has_visible_attachments

    msg = EmailMessage()
    msg.set_content("See attached")
    msg.add_attachment(b"report", maintype="application", subtype="pdf", filename="report.pdf")
    msg.add_attachment(b"tiny-logo", maintype="image", subtype="png", filename="logo.png")

    assert _has_visible_attachments(msg) is True


def test_remote_search_explicitly_checks_mime_filename_headers():
    from routes.email.email_routes import _email_imap_search_criteria

    criteria = _email_imap_search_criteria("report.pdf")
    assert "HEADER Content-Disposition" in criteria
    assert "HEADER Content-Type" in criteria


def test_attachment_cache_backfill_preserves_message_id(tmp_path, monkeypatch):
    from routes.email import email_helpers, email_routes

    db_path = tmp_path / "mail.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE email_attachment_metadata_cache (
        owner TEXT, account_key TEXT, folder TEXT, uid TEXT, message_id TEXT,
        attachments_json TEXT, updated_at TEXT,
        PRIMARY KEY (owner, account_key, folder, uid))"""
    )
    conn.execute(
        """CREATE TABLE email_message_index (
        owner TEXT, account_key TEXT, folder TEXT, uid TEXT,
        has_attachments INTEGER, attachment_names TEXT, updated_at TEXT,
        PRIMARY KEY (owner, account_key, folder, uid))"""
    )
    conn.execute(
        "INSERT INTO email_message_index VALUES (?,?,?,?,?,?,?)",
        ("felix", "acct", "INBOX", "7", 1, "old.png", "before"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(email_helpers, "SCHEDULED_DB", db_path)

    signature = [{"filename": "signature.png", "size": 1000}]
    email_routes._email_attachment_meta_cache_put(
        "felix", "acct", "INBOX", "7", "<message@example>", signature
    )
    email_routes._email_attachment_meta_cache_put(
        "felix", "acct", "INBOX", "7", "", signature
    )

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT message_id FROM email_attachment_metadata_cache").fetchone()[0] == "<message@example>"
    assert conn.execute("SELECT has_attachments FROM email_message_index").fetchone()[0] == 0
    conn.close()
