from services.memory import skill_extractor


class _FakeSession:
    session_id = "s1"

    def get_context_messages(self):
        return [
            {"role": "user", "content": "Walk me through deploying the service"},
            {"role": "assistant", "content": "Sure, here's the runbook..."},
        ]


class _FakeSkillsManager:
    def __init__(self):
        self.added = []

    def load(self, owner=None):
        return []

    def add_skill(self, **kwargs):
        self.added.append(kwargs)
        return {"id": "skill-1", **kwargs}


async def _extract(monkeypatch, response):
    async def fake_llm_call_async(*args, **kwargs):
        return response

    monkeypatch.setattr("src.llm_core.llm_call_async", fake_llm_call_async)
    skills_manager = _FakeSkillsManager()
    entry = await skill_extractor.maybe_extract_skill(
        _FakeSession(),
        skills_manager,
        endpoint_url="http://endpoint",
        model="test-model",
        headers={},
        round_count=3,
        tool_count=3,
        owner="alice",
    )
    return entry, skills_manager.added


async def test_maybe_extract_skill_recovers_json_past_stray_braces(monkeypatch):
    for response, title in (
        # A stray '{' in prose before the real object: slicing from the first
        # '{' to the last '}' produced invalid JSON and dropped the extraction.
        (
            'Sure thing, note this uses {a} as a placeholder, then the actual skill is:\n'
            '{"title": "Deploy runbook", "problem": "manual deploys are error-prone", '
            '"solution": "use the deploy script", "steps": ["build", "push", "restart"], '
            '"tags": ["deploy"], "confidence": 0.9}',
            "Deploy runbook",
        ),
        # Starts with '{' but the first fragment is invalid, so the candidate
        # walk must run even when the response starts with a brace.
        (
            '{not json}\n'
            '{"title": "Valid later", "problem": "p", "solution": "s", '
            '"steps": ["one", "two", "three"], "tags": ["test"], "confidence": 0.9}',
            "Valid later",
        ),
    ):
        entry, added = await _extract(monkeypatch, response)

        assert entry is not None and entry["title"] == title
        assert added and added[0]["title"] == title


async def test_maybe_extract_skill_drops_when_no_candidate_parses(monkeypatch):
    entry, added = await _extract(
        monkeypatch,
        'Some commentary with {unbalanced and { nested } braces } but no real JSON object',
    )

    assert entry is None
    assert not added


async def test_maybe_extract_skill_drops_on_multiple_json_objects(monkeypatch):
    entry, added = await _extract(
        monkeypatch,
        '{"title": "Deploy runbook", "problem": "manual", "solution": "script", '
        '"steps": ["build"], "tags": ["deploy"], "confidence": 0.9}\n'
        '{"title": "Unrelated skill", "problem": "manual", "solution": "script", '
        '"steps": ["build"], "tags": ["deploy"], "confidence": 0.9}',
    )

    assert entry is None
    assert not added
