"""Behavioral coverage for document editor statistics."""

from tests.helpers.node import run_node_module


def _run_stats(expression: str):
    return run_node_module(f"""
      import {{ getDocumentStats, countDocumentWords, countDocumentCharacters }}
        from './static/js/documentStats.js';
      console.log(JSON.stringify({expression}));
    """)


def test_stats_count_words_lines_characters_and_reading_time():
    assert _run_stats("getDocumentStats('Hello, world!\\nSecond line.')") == {
        "words": 4,
        "characters": 26,
        "charactersNoSpaces": 23,
        "lines": 2,
        "readingMinutes": 1,
    }


def test_stats_are_unicode_word_and_grapheme_aware():
    result = _run_stats("({ japanese: countDocumentWords('これはテストです'), emoji: countDocumentCharacters('A 👨‍👩‍👧‍👦') })")
    assert result["japanese"] > 1
    assert result["emoji"] == 3
