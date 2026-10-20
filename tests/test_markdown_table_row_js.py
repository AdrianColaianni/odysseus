"""Pin the pure splitTableRow helper (static/js/markdown/tableRow.js).

Regression: the old split filtered out every empty cell, so an intentionally
empty interior cell ("| a |  | c |") collapsed the row to 2 columns and
misaligned it with the header.
"""
import json

from tests.helpers.node import run_node_module


def _split(row):
    return run_node_module(f"""
    import {{ splitTableRow }} from './static/js/markdown/tableRow.js';
    console.log(JSON.stringify(splitTableRow({json.dumps(row)})));
    """)


def test_keeps_empty_interior_cell():
    assert _split("| a |  | c |") == ["a", "", "c"]


def test_rows_without_outer_pipes():
    assert _split("a | b | c") == ["a", "b", "c"]


def test_non_string_row_falls_back_to_empty_cell():
    assert _split(None) == [""]
    assert _split({"bad": "row"}) == [""]
