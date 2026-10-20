"""Regressions for the 2026-09-19 review fixes.

Each test fails on the pre-fix tree; see ~/odysseus-review-20260919.md.
"""
import json

from services.search import core as search_core
from src.agent_loop import _read_file_block_path, _read_file_targets_artifact
from src.turn_contract import personal_store_families, requested_capabilities


def test_briefing_phrase_does_not_hijack_personal_store():
    """A broad-briefing phrase must not route the user's own store to the Web."""
    for message, family in [
        ("is there anything new in my inbox?", "email"),
        ("check my email for news from Bob", "email"),
        ("show me my latest email updates", "email"),
        ("give me an update on my tasks", "tasks"),
        ("what's new on my calendar this week?", "calendar"),
        ("catch me up on my meetings", "calendar"),
        ("anything new in my documents?", "documents"),
        ("what should i know about my notes", "notes"),
    ]:
        capabilities = requested_capabilities(message)
        assert family in capabilities
        assert "search_browser" not in capabilities


def test_open_web_briefings_keep_their_web_route():
    """Open-web subjects that borrow a product noun keep search_browser."""
    for message in [
        "what's new in AI this week",
        "give me an update on the war in Ukraine",
        "what are the latest events in Kyiv",
        "news about the fed rate decision",
        "what should i know about rust 2.0",
        "catch me up on the latest AI news",
        "latest info on the iphone 18",
    ]:
        assert requested_capabilities(message) == frozenset({"search_browser"})


def test_personal_store_families_requires_possessive():
    assert personal_store_families("my calendar") == frozenset({"calendar"})
    assert personal_store_families("the latest events in Kyiv") == frozenset()


NGINX = {
    "title": "NGINX Documentation",
    "snippet": "Official configuration docs for NGINX",
    "url": "https://nginx.org/en/docs/",
}
IKEA = {
    "title": "BILLY Bookcase Assembly Manual",
    "snippet": "IKEA BILLY instructions PDF",
    "url": "https://ikea.com/manuals/billy",
}
FORD = {
    "title": "Ford Ranger Owner Manual",
    "snippet": "Operator manual for the Ford Ranger",
    "url": "https://ford.com/manual",
}


def test_document_lookups_accept_relevant_results():
    """Leading function words and task verbs are not the query entity."""
    for query, result in [
        ("how to configure nginx docs", NGINX),
        ("where can i find the ikea billy manual", IKEA),
        ("best guide for sourdough", {"title": "Sourdough Starter Guide",
                                      "snippet": "A complete guide to sourdough",
                                      "url": "https://ex.com/sourdough"}),
        ("nginx configuration docs", NGINX),
    ]:
        assert search_core._result_has_query_overlap(query, result) is True


def test_document_lookups_still_reject_homonyms():
    """A result naming none of the entity terms is still not evidence."""
    for query in [
        "ikea billy manual",
        "nginx docs",
        "sourdough guide",
    ]:
        assert search_core._result_has_query_overlap(query, FORD) is False


def test_read_file_block_path_accepts_json_and_bare_text():
    assert _read_file_block_path(
        json.dumps({"path": "/workspace/out/report.md"})
    ) == "/workspace/out/report.md"
    assert _read_file_block_path(
        "/workspace/out/report.md\ntrailing"
    ) == "/workspace/out/report.md"
    assert _read_file_block_path("") == ""


def test_reading_the_input_does_not_verify_the_output():
    """The forced read-back must target the deliverable, not the source."""
    target = "/workspace/out/report.md"
    assert _read_file_targets_artifact(json.dumps({"path": target}), target)
    assert _read_file_targets_artifact(json.dumps({"path": "./report.md"}), target)
    assert not _read_file_targets_artifact(
        json.dumps({"path": "/workspace/input/data.csv"}), target
    )
    assert not _read_file_targets_artifact(json.dumps({"path": target}), None)
