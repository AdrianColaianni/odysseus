"""Fixture reader responses preserve the authenticated account selection."""
import json

import pytest
from tests.helpers.routes import route_endpoint


@pytest.mark.asyncio
async def test_fixture_read_preserves_selected_account_for_reply(tmp_path, monkeypatch):
    import routes.email.email_routes as module
    monkeypatch.setenv('ODYSSEUS_EMAIL_FIXTURE', '1')
    monkeypatch.setattr(module, 'FIXTURE_EMAIL_MESSAGES_FILE', str(tmp_path / 'fixture_email_messages.json'))
    (tmp_path / 'fixture_email_messages.json').write_text(json.dumps({'messages': [
        {'owner': 'fixture-owner', 'uid': '10', 'account_id': 'primary-inbox',
         'subject': 'Picnic', 'body': 'Join us Saturday', 'folder': 'INBOX'},
    ]}))
    router = module.setup_email_routes()
    read = route_endpoint(router, '/api/email/read/{uid}', 'GET')
    result = await read(uid='10', folder='INBOX', account_id='validated-account',
                        mark_seen=False, full=False, owner='fixture-owner')
    assert result['account_id'] == 'validated-account'
    assert result['body'] == 'Join us Saturday'


@pytest.mark.asyncio
async def test_ai_reply_still_checks_selected_account_before_generation(monkeypatch):
    import routes.email.email_routes as module
    from fastapi import HTTPException
    checked = []

    def check(account_id, owner):
        checked.append((account_id, owner))
        raise HTTPException(404, 'Account not found')

    monkeypatch.setattr(module, '_assert_owns_account', check)
    router = module.setup_email_routes()
    reply = route_endpoint(router, '/api/email/ai-reply', 'POST')
    result = await reply({'account_id': 'missing-account', 'original_body': 'Hello'}, owner='fixture-owner')
    assert checked == [('missing-account', 'fixture-owner')]
    assert result['success'] is False
    assert 'Account not found' in result['error']
