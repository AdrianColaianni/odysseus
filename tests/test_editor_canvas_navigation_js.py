import json
import textwrap
from pathlib import Path
from tests.helpers.node import run_node_module


ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "static/js/editor/canvas-navigation.js").as_uri()


def run_node(body: str):
    script = textwrap.dedent(
        f"""
        import {{
          applyCanvasPan, isDirectPanIntent, nextPanOffset, syncPanCursor,
        }} from {json.dumps(MODULE)};
        {body}
        """
    )
    return run_node_module(script)


def test_pan_intent_covers_hand_space_and_middle_mouse():
    result = run_node(
        """
        console.log(JSON.stringify({
          hand:isDirectPanIntent('hand',false,0),
          space:isDirectPanIntent('brush',true,0),
          middle:isDirectPanIntent('brush',false,1),
          brush:isDirectPanIntent('brush',false,0),
        }));
        """
    )
    assert result == {"hand": True, "space": True, "middle": True, "brush": False}


def test_pan_math_uses_drag_origin_instead_of_accumulating_deltas():
    result = run_node(
        """
        const first = nextPanOffset({x:100,y:80},{x:12,y:-5},{x:145,y:110});
        const second = nextPanOffset({x:100,y:80},{x:12,y:-5},{x:90,y:60});
        console.log(JSON.stringify({first,second}));
        """
    )
    assert result == {
        "first": {"x": 57, "y": 25},
        "second": {"x": 2, "y": -25},
    }


def test_apply_pan_updates_state_canvas_overlay_and_cursor_classes():
    result = run_node(
        """
        const classes = new Set();
        const area = {
          dataset:{},
          classList:{
            toggle(name,on) { if (on) classes.add(name); else classes.delete(name); },
          },
        };
        const state = {
          tool:'hand', spacePanActive:false,
          mainCanvas:{style:{}}, transformOverlay:{style:{}},
        };
        applyCanvasPan(state,area,17,-9);
        syncPanCursor(state,area,false);
        const ready = [...classes];
        syncPanCursor(state,area,true);
        console.log(JSON.stringify({
          pan:[state.panX,state.panY], dataset:area.dataset,
          main:state.mainCanvas.style.transform,
          overlay:state.transformOverlay.style.transform,
          ready, panning:[...classes],
        }));
        """
    )
    assert result["pan"] == [17, -9]
    assert result["dataset"] == {"panX": "17", "panY": "-9"}
    assert result["main"] == "translate3d(17px, -9px, 0)"
    assert result["overlay"] == result["main"]
    assert result["ready"] == ["ge-pan-ready"]
    assert result["panning"] == ["ge-panning"]
