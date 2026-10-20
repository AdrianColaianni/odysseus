def test_skill_list_summary_persists_clickable_skill_anchors():
    from src.agent_loop import _skills_list_summary_from_tool_output

    summary = _skills_list_summary_from_tool_output(
        "\n".join(
            [
                "## Published",
                "- **open-a-youtube-creator-s-latest-video** (general): Open a YouTube creator's latest video",
                "## Drafts",
                "- **audit-fixture-20260828-skills-search** [draft]: domain audit fixture",
            ]
        )
    )

    assert "[open-a-youtube-creator-s-latest-video](#skill-open-a-youtube-creator-s-latest-video)" in summary
    assert "[audit-fixture-20260828-skills-search](#skill-audit-fixture-20260828-skills-search)" in summary
    assert "**open-a-youtube-creator-s-latest-video**" not in summary


def test_memory_list_summary_persists_clickable_memory_anchors():
    from src.agent_loop import _memory_list_summary_from_tool_output

    summary = _memory_list_summary_from_tool_output(
        "\n".join(
            [
                "Found 2 memory entries:",
                "",
                "- [preference] `abc12345` — Use short replies.",
                "- [project] `def67890` — Working on Odysseus SFT traces.",
            ]
        )
    )

    assert "[preference abc12345](#memory-abc12345)" in summary
    assert "[project def67890](#memory-def67890)" in summary
    assert "`abc12345`" not in summary
