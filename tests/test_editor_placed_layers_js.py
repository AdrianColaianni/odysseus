import json
import textwrap
from pathlib import Path
from tests.helpers.node import run_node_module


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "static/js/editor/placed-layer.js").as_uri()


def test_affine_composition_and_bounds_preserve_source_geometry():
    data = run_node_module(textwrap.dedent(f"""
        import {{ affineBounds, frameTransformMatrix, initialPlacedMatrix, multiplyAffine }} from {json.dumps(MODULE)};
        const initial = initialPlacedMatrix(400, 200, {{ x: 10, y: 20, width: 200, height: 100 }});
        const bounds = {{ ...affineBounds(initial, 400, 200), centerX: 110, centerY: 70 }};
        const frame = frameTransformMatrix(bounds, {{ width: 100, height: 50, centerX: 250, centerY: 150, rotation: 90, flipH: false, flipV: false }});
        const matrix = multiplyAffine(frame, initial);
        console.log(JSON.stringify({{ initial, result: affineBounds(matrix, 400, 200) }}));
    """))
    assert data["initial"] == [0.5, 0, 0, 0.5, 10, 20]
    assert data["result"] == {"x": 225, "y": 100, "width": 50, "height": 100, "centerX": 250, "centerY": 150}


def test_replacement_matrix_keeps_document_corners():
    data = run_node_module(textwrap.dedent(f"""
        import {{ normalizeAffine, transformPoint }} from {json.dumps(MODULE)};
        const oldW = 400, oldH = 200, newW = 800, newH = 100;
        const [a,b,c,d,e,f] = normalizeAffine([0.5, 0.2, -0.1, 0.6, 30, 40]);
        const next = [a*oldW/newW,b*oldW/newW,c*oldH/newH,d*oldH/newH,e,f];
        const oldCorners = [[0,0],[oldW,0],[oldW,oldH],[0,oldH]].map(([x,y]) => transformPoint([a,b,c,d,e,f],x,y));
        const newCorners = [[0,0],[newW,0],[newW,newH],[0,newH]].map(([x,y]) => transformPoint(next,x,y));
        console.log(JSON.stringify({{ oldCorners, newCorners }}));
    """))
    assert data["newCorners"] == data["oldCorners"]
