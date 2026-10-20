import asyncio

import pytest

from routes import skills_routes as routes
from services.skills import agent_runner, audit_workflow
from services.skills.dependencies import default_dependencies


def test_audit_stream_errors_are_not_skill_evidence(monkeypatch):
    for frame in (
        'event: error\ndata: {"error":"upstream unavailable","status":503}\n\n',
        'data: {"type":"error","message":"connection failed"}\n\n',
    ):
        async def stream(*args, **kwargs):
            yield frame

        monkeypatch.setattr("src.agent_loop.stream_agent_loop", stream)
        with pytest.raises(agent_runner.SkillAuditUnavailable):
            asyncio.run(agent_runner.run_audit_arm([], "url", "model", {}, "alice"))


def test_unavailable_model_stops_batch_without_recording_verdict(monkeypatch):
    visited = []

    class Skills:
        def load(self, owner=None):
            return [{"name": "first"}, {"name": "second"}]

        def set_audit(self, *args, **kwargs):
            pytest.fail("An infrastructure failure must not update the skill verdict")

    async def audit(manager, skill, *args, **kwargs):
        visited.append(skill["name"])
        raise agent_runner.SkillAuditUnavailable("offline")

    monkeypatch.setattr(audit_workflow, "audit_one_skill", audit)
    job = {"status": "running", "log": [], "results": [], "done": 0}
    monkeypatch.setattr(audit_workflow, "_skill_audit_jobs", {("alice",): job})
    asyncio.run(default_dependencies().run_batch(("alice",), Skills(), ["first", "second"],
                                        "url", "model", {}, None, "alice"))
    assert visited == ["first"]
    assert job["status"] == "error"
    assert job["unavailable"] == "offline"
    assert job["done"] == 0
    assert job["results"] == []
