"""Checklist follow-ups through the public tool and a disposable real database."""
import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import database
from src.tools.notes import do_manage_notes


@pytest.fixture
def checklist(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'checklists.db'}")
    database.Note.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    with factory() as db:
        db.add(database.Note(id="checklist-fixture", owner="sft_checklist", title="Fixture",
                             note_type="checklist", items=json.dumps([
                                 {"text": "tea", "done": False},
                                 {"text": "rice", "done": True},
                             ])))
        db.commit()
    yield "checklist-fixture"
    engine.dispose()


def call(note_id, action="view", owner="sft_checklist", **args):
    return asyncio.run(do_manage_notes(json.dumps({"action": action, "id": note_id, **args}), owner=owner))


def test_explicit_checked_state_is_idempotent(checklist):
    before = call(checklist)
    for _ in range(2):
        result = call(checklist, "toggle_item", index=1, done=True)
        assert result["exit_code"] == 0
        assert call(checklist) == before


def test_toggle_requires_explicit_integer_index(checklist):
    before = call(checklist)
    for args in ({}, {'index': True}, {'index': '0'}):
        result = call(checklist, 'toggle_item', done=True, **args)
        assert result['exit_code'] == 1, args
        assert 'index' in result['error']
    assert call(checklist) == before


def test_invalid_target_state_does_not_change_checklist(checklist):
    before = call(checklist)
    for done in ("false", 1, None):
        result = call(checklist, "toggle_item", index=1, done=done)
        assert result["exit_code"] == 1, done
        assert "boolean" in result["error"]
    assert call(checklist) == before


def test_explicit_uncheck_then_legacy_toggle(checklist):
    for _ in range(2):
        assert call(checklist, "toggle_item", index=1, done=False)["exit_code"] == 0
        assert "[ ] 1: rice" in call(checklist)["results"]
    assert call(checklist, "toggle_item", index=1)["exit_code"] == 0
    assert "[x] 1: rice" in call(checklist)["results"]
    assert call(checklist, "toggle_item", index=1)["exit_code"] == 0
    assert "[ ] 1: rice" in call(checklist)["results"]


def test_invalid_index_or_owner_does_not_change_checklist(checklist):
    before = call(checklist)
    for args in ({"index": -1}, {"index": 2}, {"owner": "other_owner", "index": 1}):
        assert call(checklist, "toggle_item", done=False, **args)["exit_code"] == 1, args
    assert call(checklist) == before


def test_remove_item_never_silently_toggles_checked_state(checklist):
    before = call(checklist)
    result = call(checklist, "remove_item", index=1)
    assert result["exit_code"] == 1
    assert "update" in result["error"]
    assert call(checklist) == before
    # Follow the canonical replacement contract, then undo without losing state.
    assert call(checklist, "update", checklist_items=[{"text": "tea", "done": False}])["exit_code"] == 0
    assert "rice" not in call(checklist)["results"]
    assert call(checklist, "update", checklist_items=[
        {"text": "tea", "done": False}, {"text": "rice", "done": True},
    ])["exit_code"] == 0
    assert call(checklist) == before


def test_malformed_checklist_creation_saves_nothing(checklist):
    with database.SessionLocal() as db:
        before = db.query(database.Note).count()
    for items in (None, 'drop keys, meeting 2pm', [{'text': ''}], [{'text': 'keys', 'done': 'false'}]):
        args = {'note_type': 'checklist', 'title': 'Tasks hidden in title'}
        if items is not None:
            args['checklist_items'] = items
        result = asyncio.run(do_manage_notes(json.dumps({'action': 'add', **args}), owner='sft_checklist'))
        assert result['exit_code'] == 1, items
    with database.SessionLocal() as db:
        assert db.query(database.Note).count() == before


def test_add_with_existing_id_never_creates_duplicate(checklist):
    before = call(checklist)
    for key in ('id', 'note_id', 'noteId'):
        result = asyncio.run(do_manage_notes(json.dumps({
            'action': 'add', key: checklist, 'note_type': 'checklist',
            'checklist_items': [{'text': 'New task', 'done': False}],
        }), owner='sft_checklist'))
        assert result['exit_code'] == 1, key
    assert call(checklist) == before
    with database.SessionLocal() as db:
        assert db.query(database.Note).count() == 1


def test_checklist_default_title_uses_user_local_date(checklist, monkeypatch):
    from datetime import datetime, timezone, timedelta
    import src.user_time
    monkeypatch.setattr(src.user_time, 'now_user_local', lambda: datetime(
        2026, 9, 30, 0, 30, tzinfo=timezone(timedelta(hours=2))))
    result = asyncio.run(do_manage_notes(json.dumps({
        'action': 'add', 'note_type': 'checklist',
        'checklist_items': [{'text': 'Meeting 2pm', 'done': False}],
    }), owner='sft_checklist'))
    assert result['exit_code'] == 0
    assert result['note_title'] == 'To-do - 2026-09-30'
    assert 'Meeting 2pm' in call(result['note_id'])['results']
