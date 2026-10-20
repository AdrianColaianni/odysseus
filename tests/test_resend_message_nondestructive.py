from types import SimpleNamespace

from routes.history.history_routes import _keep_count_before_message


def test_truncate_can_resolve_keep_count_from_db_message_id():
    rows = [
        SimpleNamespace(id="first"),
        SimpleNamespace(id="clicked-user"),
        SimpleNamespace(id="assistant-after"),
    ]

    assert _keep_count_before_message(rows, "clicked-user") == 1
    assert _keep_count_before_message(rows, "missing") is None
    assert _keep_count_before_message(rows, "") is None
