"""Pin computeSnap (static/js/editor/snap.js) against a non-array otherLayers."""
import json

from tests.helpers.node import run_node_module

_IMPORT = "import { computeSnap } from './static/js/editor/snap.js';\n"


def _snap(other_layers):
    return run_node_module(_IMPORT + f"""
    const layer = {{ id: 'L1', canvas: {{ width: 100, height: 50 }} }};
    const ctx = {{ zoom: 1, canvasW: 800, canvasH: 600, otherLayers: {json.dumps(other_layers)} }};
    console.log(JSON.stringify(computeSnap(layer, 10, 10, ctx)));
    """)


def test_compute_snap_tolerates_non_array_other_layers():
    # ctx.otherLayers should be an array, but during init / error recovery it
    # can be missing or wrong-typed; the old `for...of` threw on a non-iterable.
    r = _snap(123)
    assert r["x"] == 10 and r["y"] == 10 and r["guides"] == []


def test_compute_snap_tolerates_missing_layer_or_context():
    assert run_node_module(_IMPORT + """
    console.log(JSON.stringify([
      computeSnap(null, 10, 20, { zoom: 1, canvasW: 800, canvasH: 600 }),
      computeSnap({ id: 'L1' }, 11, 21, { zoom: 1, canvasW: 800, canvasH: 600 }),
      computeSnap({ id: 'L1', canvas: { width: 100, height: 50 } }, 12, 22, null)
    ]));
    """) == [
        {"x": 10, "y": 20, "guides": []},
        {"x": 11, "y": 21, "guides": []},
        {"x": 12, "y": 22, "guides": []},
    ]


def test_compute_snap_still_snaps_to_a_layer_edge():
    other = [{"id": "L2", "visible": True, "offset": {"x": 12, "y": 300},
              "canvas": {"width": 100, "height": 50}}]
    r = _snap(other)
    assert r["x"] == 12
