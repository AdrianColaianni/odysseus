"""Stopping a stream: detached runs survive a disconnect, Compare panes do not.

A subscriber disconnecting must not stop a detached run; only stop() does, and
the wrapped generator's CancelledError handler fires once. Compare panes are
never detached, so closing the SSE cancels the upstream call.
"""
import asyncio

import pytest

from src import agent_runs
from routes import chat_routes


# --------------------------------------------------------------------------- #
# Fakes that mirror the contract `stream_with_save()` relies on: the wrapped
# generator accumulates `full_response` as it yields chunks, and on
# cancellation (asyncio.CancelledError / GeneratorExit, the same exceptions
# Starlette raises into a streaming generator when the client disconnects)
# saves the partial response exactly once via its `except` handler — mirroring
# the real except (asyncio.CancelledError, GeneratorExit): blocks in
# routes/chat_routes.py.
# --------------------------------------------------------------------------- #
class _FakeSaveSink:
    """Records save_partial() calls so tests can assert "saved exactly once"."""

    def __init__(self):
        self.saves = []
        self.completions = []

    def save_partial(self, text):
        self.saves.append(text)

    def save_complete(self, text):
        self.completions.append(text)


def _make_stream_with_save(sink, chunks, *, hang_after=None):
    """Build an async generator that mirrors stream_with_save()'s shape:
    streams `chunks`, accumulating into `full_response`, and on
    CancelledError/GeneratorExit saves the partial exactly once before
    re-raising (so agent_runs._drain's `await agen.aclose()` sees it run).

    `hang_after`: if set, after yielding that many chunks the generator
    awaits an Event that's never set — simulating a slow/silent upstream
    so cancellation must interrupt an in-flight await, not just be noticed
    between chunks.
    """
    async def gen():
        full_response = ""
        try:
            for i, chunk in enumerate(chunks):
                if hang_after is not None and i == hang_after:
                    await asyncio.Event().wait()  # never resolves on its own
                full_response += chunk
                yield f"data: {chunk}\n\n"
            sink.save_complete(full_response)
            yield "data: [DONE]\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            if full_response:
                sink.save_partial(full_response)
            raise
    return gen()


async def _collect_subscription(session_id, expected_run=None):
    return [
        event
        async for event in agent_runs.subscribe(session_id, expected_run)
    ]


# --------------------------------------------------------------------------- #
# agent_runs: detached-run semantics (what NORMAL chat/agent streams use)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_detached_run_keeps_going_after_subscriber_disconnects():
    """A subscriber dropping (client closes tab/SSE) must NOT stop a detached
    run — that's the whole point of agent_runs. Only stop()/cancel does."""
    sink = _FakeSaveSink()
    session_id = "sess-detached-1"
    agent_runs._RUNS.pop(session_id, None)

    chunks = ["hello", " world", "!"]
    agen = _make_stream_with_save(sink, chunks)
    run = agent_runs.start(session_id, agen)

    # Subscribe, then immediately disconnect (simulate the client closing the
    # SSE) — by simply breaking out of the async-for over subscribe().
    sub = agent_runs.subscribe(session_id)
    async for _ in sub:
        break
    await sub.aclose()

    # The run must still be active / finish on its own — not stopped by the
    # subscriber going away.
    await run.task
    assert run.status == "done"
    assert sink.completions == ["hello world!"]
    assert sink.saves == []  # completed normally — no partial save


@pytest.mark.asyncio
async def test_stop_cancels_detached_run_and_saves_partial_exactly_once():
    """agent_runs.stop() (the Stop button's real backend call for detached
    runs) cancels the in-flight generator promptly — including while it is
    awaiting the next chunk — and the partial is saved exactly once."""
    sink = _FakeSaveSink()
    session_id = "sess-detached-2"
    agent_runs._RUNS.pop(session_id, None)

    chunks = ["partial-a", "partial-b", "partial-c"]
    # Hang after the 2nd chunk so cancellation must interrupt an in-flight
    # await — not just be noticed between already-arrived chunks.
    agen = _make_stream_with_save(sink, chunks, hang_after=2)
    run = agent_runs.start(session_id, agen)

    # Let it stream the first two chunks, then get stuck on the third.
    received = []
    sub = agent_runs.subscribe(session_id)
    async for ev in sub:
        received.append(ev)
        if len(received) >= 2:
            break
    await sub.aclose()

    stopped = agent_runs.stop(session_id, run.run_id)
    assert stopped is True

    await run.task  # propagates promptly — not stuck on the hung await
    assert run.status == "stopped"

    # Saved exactly once, with exactly the chunks that arrived before the hang.
    assert sink.saves == ["partial-apartial-b"]
    assert sink.completions == []


@pytest.mark.asyncio
async def test_normal_completion_saves_exactly_once_not_partial():
    """Regression: a stream that finishes normally (no disconnect, no stop)
    saves via the completion path exactly once, and never via the
    partial/cancellation path."""
    sink = _FakeSaveSink()
    session_id = "sess-detached-3"
    agent_runs._RUNS.pop(session_id, None)

    agen = _make_stream_with_save(sink, ["one", "two", "three"])
    run = agent_runs.start(session_id, agen)
    await run.task

    assert run.status == "done"
    assert sink.completions == ["onetwothree"]
    assert sink.saves == []


@pytest.mark.asyncio
async def test_detached_run_identity_is_stable_for_replay_and_unique_per_run():
    session_id = "sess-detached-run-identity"
    agent_runs._RUNS.pop(session_id, None)

    first = agent_runs.start(session_id, _make_stream_with_save(_FakeSaveSink(), ["one"]))
    first_id = first.run_id
    assert agent_runs._RUNS[session_id].run_id == first_id
    await first.task
    assert agent_runs._RUNS[session_id].run_id == first_id

    second = agent_runs.start(session_id, _make_stream_with_save(_FakeSaveSink(), ["two"]))
    assert second.run_id != first_id
    assert agent_runs._RUNS[session_id].run_id == second.run_id
    await second.task


@pytest.mark.asyncio
async def test_lazy_subscription_stays_bound_to_header_run_after_replacement():
    session_id = "sess-detached-lazy-subscription"
    agent_runs._RUNS.pop(session_id, None)

    async def stream(label):
        yield f'data: {{"delta":"{label}"}}\n\n'

    first = agent_runs.start(session_id, stream("first"))
    await first.task
    # StreamingResponse does not iterate its body until after construction.
    # Capture the same exact run object used for its identity header.
    lazy_body = agent_runs.subscribe(session_id, first)

    second = agent_runs.start(session_id, stream("second"))
    await second.task

    replayed = [event async for event in lazy_body]
    assert replayed == ['data: {"delta":"first"}\n\n']
    assert agent_runs._RUNS[session_id].run_id == second.run_id


@pytest.mark.asyncio
async def test_stale_run_identity_cannot_stop_replacement_run():
    session_id = "sess-detached-stale-stop"
    agent_runs._RUNS.pop(session_id, None)
    release = asyncio.Event()

    async def finished():
        yield 'data: {"delta":"old"}\n\n'

    async def replacement():
        yield 'data: {"delta":"new"}\n\n'
        await release.wait()

    first = agent_runs.start(session_id, finished())
    await first.task
    second = agent_runs.start(session_id, replacement())
    await asyncio.sleep(0)

    assert agent_runs.stop(session_id) is False
    assert agent_runs.stop(session_id, first.run_id) is False
    assert second.task is not None and not second.task.done()
    assert agent_runs.stop(session_id, second.run_id) is True
    await second.task


@pytest.mark.asyncio
async def test_triple_replacement_closes_middle_subscriber_and_preserves_save_order():
    session_id = "sess-detached-triple-replacement"
    agent_runs._RUNS.pop(session_id, None)
    first_closing = asyncio.Event()
    release_first = asyncio.Event()
    third_started = asyncio.Event()

    async def first_stream():
        try:
            yield 'data: {"delta":"first"}\n\n'
            await asyncio.Event().wait()
        finally:
            first_closing.set()
            await release_first.wait()

    async def middle_stream():
        yield 'data: {"delta":"middle"}\n\n'

    async def third_stream():
        third_started.set()
        yield 'data: {"delta":"third"}\n\n'

    first = agent_runs.start(session_id, first_stream())
    while not first.buffer:
        await asyncio.sleep(0)

    middle = agent_runs.start(session_id, middle_stream())
    await first_closing.wait()
    assert middle.task is not None and not middle.task.done()

    middle_events_task = asyncio.create_task(
        _collect_subscription(session_id, middle)
    )
    while not middle.subscribers:
        await asyncio.sleep(0)

    third = agent_runs.start(session_id, third_stream())

    # The superseded middle response closes immediately even though its task
    # remains as the transitive barrier for the first run's partial save.
    assert await asyncio.wait_for(middle_events_task, timeout=1) == []
    assert middle.status == "stopped"
    assert middle.task is not None and not middle.task.done()
    assert not third_started.is_set()

    release_first.set()
    await asyncio.wait_for(first.task, timeout=1)
    await asyncio.wait_for(middle.task, timeout=1)
    await asyncio.wait_for(third.task, timeout=1)

    assert first.status == "stopped"
    assert middle.status == "stopped"
    assert third.status == "done"
    assert third_started.is_set()


@pytest.mark.asyncio
async def test_reconnect_replays_pinned_fallback_run_without_restarting_tools():
    session_id = "sess-detached-fallback-resume"
    agent_runs._RUNS.pop(session_id, None)
    release = asyncio.Event()
    tool_executions = 0
    fallback = 'data: {"type":"fallback","answered_by":"backup","candidate_index":1}\n\n'
    tool = 'data: {"type":"tool_output","tool":"bash","output":"ok"}\n\n'

    async def pinned_run():
        nonlocal tool_executions
        yield fallback
        tool_executions += 1
        yield tool
        await release.wait()
        yield 'data: {"delta":"backup finished"}\n\n'
        yield "data: [DONE]\n\n"

    run = agent_runs.start(session_id, pinned_run())
    first = agent_runs.subscribe(session_id)
    first_events = []
    async for event in first:
        first_events.append(event)
        if len(first_events) == 2:
            break
    await first.aclose()

    assert run.status == "running"
    assert tool_executions == 1
    assert agent_runs._RUNS[session_id] is run

    resumed_events = []
    resumed = agent_runs.subscribe(session_id)
    async for event in resumed:
        resumed_events.append(event)
        if len(resumed_events) == 2:
            release.set()
    await run.task

    assert resumed_events[:2] == [fallback, tool]
    assert resumed_events[-1] == "data: [DONE]\n\n"
    assert tool_executions == 1
    assert agent_runs._RUNS[session_id] is run


def test_only_resumable_interactive_streams_are_detached():
    for compare_mode, runtime_context, expected in (
        (False, {}, True),
        (False, {"surface": "odysseus-tui"}, True),
        (True, {}, False),
        (False, {"surface": "odysseus-native", "unattended_mode": True}, False),
    ):
        assert chat_routes._should_detach_chat_stream(
            compare_mode=compare_mode,
            client_runtime_context=runtime_context,
        ) is expected, (compare_mode, runtime_context)


def test_unattended_streams_do_not_launch_post_response_llm_jobs():
    for tools_blocked, approval_continuation, runtime_context, expected in (
        (False, False, {}, True),
        (True, False, {}, False),
        (False, True, {}, False),
        (False, False, {"surface": "odysseus-native"}, True),
        (False, False, {"surface": "odysseus-native", "unattended_mode": True}, False),
        (False, False, {"surface": "odysseus-tui", "unattended_mode": True}, False),
    ):
        assert chat_routes._post_response_extraction_allowed(
            tools_blocked=tools_blocked,
            tool_approval_continuation=approval_continuation,
            client_runtime_context=runtime_context,
        ) is expected, (tools_blocked, approval_continuation, runtime_context)
