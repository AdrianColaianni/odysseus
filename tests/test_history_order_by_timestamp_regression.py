"""Regression guard for #1659.

`routes/history_routes.py` ordered three ChatMessage queries by
``DbChatMessage.created_at`` — the mark-stopped (`:268`), update-last-meta
(`:323`) and merge-last-assistant (`:404`) handlers. The ``ChatMessage`` model
does **not** inherit ``TimestampMixin`` and exposes only a ``timestamp`` column,
so ``DbChatMessage.created_at`` raised ``AttributeError`` at query-build time ->
HTTP 500 on Stop, last-message metadata updates, and Continue/merge.

These tests pin that the model has ``timestamp`` and no ``created_at``, and
that ``routes/history_routes.py`` never orders a ChatMessage query by the
non-existent ``created_at`` column again.
"""
from pathlib import Path

from core.database import ChatMessage as DbChatMessage


HISTORY_ROUTES = Path(__file__).resolve().parent.parent / "routes" / "history" / "history_routes.py"


def test_chatmessage_model_has_timestamp_not_created_at():
    assert hasattr(DbChatMessage, "timestamp"), "ChatMessage should expose a `timestamp` column"
    assert not hasattr(DbChatMessage, "created_at"), (
        "ChatMessage does not inherit TimestampMixin; ordering by `created_at` "
        "raises AttributeError -> HTTP 500 (#1659)"
    )


def test_history_routes_do_not_order_by_created_at():
    text = HISTORY_ROUTES.read_text(encoding="utf-8")
    assert "DbChatMessage.created_at" not in text, (
        "history_routes must order ChatMessage queries by `.timestamp`, not the "
        "non-existent `.created_at` column (raises AttributeError -> HTTP 500, #1659)"
    )
