from src.deep_research import CATEGORY_PROMPTS, _infer_research_category
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
from src.visual_report import _standard_visual_variant


def _tool_schema(name: str) -> dict:
    return next(
        schema["function"]
        for schema in FUNCTION_TOOL_SCHEMAS
        if schema.get("function", {}).get("name") == name
    )


def test_visual_research_mode_is_removed_from_prompt_and_tool_schema():
    category_schema = _tool_schema("trigger_research")["parameters"]["properties"]["category"]
    rounds_schema = _tool_schema("trigger_research")["parameters"]["properties"]["max_rounds"]

    assert "visual" not in category_schema["enum"]
    assert rounds_schema["minimum"] == 0
    assert "visual" not in CATEGORY_PROMPTS


def test_auto_format_uses_strong_intent_before_llm():
    cases = [
        ("Best home cinema speakers in 2026", "product"),
        ("Compare Scala with Kotlin and Clojure", "comparison"),
        ("How to configure SearXNG step by step", "howto"),
        ("Fact-check the claim that coffee dehydrates you", "factcheck"),
        ("Explain how a transformer neural network works", None),
        ("Show the carbon cycle as a diagram", None),
    ]
    for question, expected in cases:
        assert _infer_research_category(question) == expected, question


def test_standard_reports_use_one_format_palette():
    assert _standard_visual_variant("first report", "rp-one") == 0
    assert _standard_visual_variant("completely different report", "rp-two") == 0
